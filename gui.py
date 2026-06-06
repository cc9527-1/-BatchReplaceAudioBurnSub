#!/usr/bin/env python3
"""
AI Video Merge Tool v4.0
- Batch: remove original audio + replace with translated audio + burn/embed subtitles + upscale
- AMD GPU (hevc_amf) hardware encoding
- Parallel multi-stream encoding
- Voice enhancement EQ presets
- Smart file matching (numbered prefix or similarity)
- Real-time progress with fallback timing
"""

import os
import sys
import re
import json
import time
import struct
import subprocess
import threading
import concurrent.futures
from pathlib import Path
from difflib import SequenceMatcher

# ─── FFmpeg / FFprobe finder ────────────────────────────────────────────────

def find_ffmpeg():
    """Find ffmpeg.exe, raise immediately if not found."""
    candidates = [
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ffmpeg', 'ffmpeg-8.0.1-essentials_build', 'bin', 'ffmpeg.exe'),
        os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Local', 'ffmpeg', 'ffmpeg-8.0.1-essentials_build', 'bin', 'ffmpeg.exe'),
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'D:\ffmpeg\bin\ffmpeg.exe',
    ]
    # Also check PATH
    pathext = os.environ.get('PATH', '')
    for d in pathext.split(os.pathsep):
        candidates.append(os.path.join(d, 'ffmpeg.exe'))
    
    for c in candidates:
        c = c.strip()
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "FFmpeg not found!\n"
        "Please install FFmpeg and add to PATH, or place at:\n"
        "  %LOCALAPPDATA%\\ffmpeg\\ffmpeg-8.0.1-essentials_build\\bin\\ffmpeg.exe"
    )

def find_ffprobe():
    """Find ffprobe.exe next to ffmpeg."""
    ffmpeg_path = find_ffmpeg()
    ffprobe_path = ffmpeg_path.replace('ffmpeg.exe', 'ffprobe.exe')
    if os.path.isfile(ffprobe_path):
        return ffprobe_path
    return None

# ─── File matching ──────────────────────────────────────────────────────────

VIDEO_EXT = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.ts'}
AUDIO_EXT = {'.mp3', '.m4a', '.aac', '.wav', '.ogg', '.flac'}
SUB_EXT   = {'.srt', '.ass', '.ssa', '.vtt'}

AUDIO_TAGS = ['_translated', '_翻译', '_zh', '_cn', '_chinese', '_中文']
SUB_TAGS   = ['_translated', '_翻译', '_zh', '_cn', '_chinese', '_中文']

def normalize_name(name):
    """Normalize filename for matching: remove tags, unify quotes/spaces."""
    name = name.strip()
    # Fullwidth -> ASCII
    name = name.replace('\u3000', ' ')  # fullwidth space
    name = name.replace('\uff02', '"')   # fullwidth quote
    name = name.replace('\u201c', '"').replace('\u201d', '"')  # curly quotes
    name = name.replace('\u2018', "'").replace('\u2019', "'")  # curly single
    return name.strip()

def strip_number_prefix(name):
    """Remove leading NNN prefix like '001 ' or '01 - '."""
    m = re.match(r'^(\d{1,3}[\s.\-_]*)', name)
    if m:
        return name[m.end():]
    return name

def get_base_name(filename):
    """Get base name without extension and without language tags."""
    stem = Path(filename).stem
    stem = normalize_name(stem)
    # Remove language tags
    for tag in AUDIO_TAGS + SUB_TAGS:
        if stem.lower().endswith(tag.lower()):
            stem = stem[:-len(tag)]
    return stem.strip()

def has_audio_tag(filename):
    stem = Path(filename).stem.lower()
    return any(stem.endswith(t.lower()) for t in AUDIO_TAGS)

def has_sub_tag(filename):
    stem = Path(filename).stem.lower()
    return any(stem.endswith(t.lower()) for t in SUB_TAGS)

def match_files(video_files, audio_files, sub_files):
    """Smart matching: numbered prefix exact -> similarity scoring."""
    result = []
    used_audio = set()
    used_sub = set()
    
    for vf in video_files:
        vstem = Path(vf).stem
        vnorm = normalize_name(vstem)
        vbase = get_base_name(vf)
        # Try numbered prefix match
        m = re.match(r'^(\d{1,3})', vstem)
        vnum = m.group(1) if m else None
        
        best_audio = None
        best_audio_score = 0
        best_sub = None
        best_sub_score = 0
        
        for i, af in enumerate(audio_files):
            if i in used_audio:
                continue
            astem = Path(af).stem
            abase = get_base_name(af)
            
            # Numbered prefix exact match
            if vnum:
                am = re.match(r'^(\d{1,3})', astem)
                if am and am.group(1) == vnum and has_audio_tag(af):
                    score = 1000 + int(vnum)
                    if score > best_audio_score:
                        best_audio = i
                        best_audio_score = score
                    continue
            
            # Similarity match
            score = SequenceMatcher(None, vbase.lower(), abase.lower()).ratio() * 100
            if score > best_audio_score and has_audio_tag(af):
                best_audio = i
                best_audio_score = score
        
        for i, sf in enumerate(sub_files):
            if i in used_sub:
                continue
            sstem = Path(sf).stem
            sbase = get_base_name(sf)
            
            if vnum:
                sm = re.match(r'^(\d{1,3})', sstem)
                if sm and sm.group(1) == vnum and has_sub_tag(sf):
                    score = 1000 + int(vnum)
                    if score > best_sub_score:
                        best_sub = i
                        best_sub_score = score
                    continue
            
            score = SequenceMatcher(None, vbase.lower(), sbase.lower()).ratio() * 100
            if score > best_sub_score and has_sub_tag(sf):
                best_sub = i
                best_sub_score = score
        
        amatch = audio_files[best_audio] if best_audio is not None and best_audio_score > 40 else None
        smatch = sub_files[best_sub] if best_sub is not None and best_sub_score > 40 else None
        
        if best_audio is not None and amatch:
            used_audio.add(best_audio)
        if best_sub is not None and smatch:
            used_sub.add(best_sub)
        
        result.append({
            'video': vf,
            'audio': amatch,
            'sub': smatch,
            'audio_score': best_audio_score if best_audio is not None else 0,
            'sub_score': best_sub_score if best_sub is not None else 0,
        })
    
    return result

# ─── Video duration probe ──────────────────────────────────────────────────

def get_video_duration(video_path, ffprobe_path):
    """Get video duration in seconds. Returns None on failure."""
    if not ffprobe_path:
        return None
    try:
        cmd = [
            ffprobe_path, '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', video_path
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=10,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        fmt = data.get('format', {})
        dur = fmt.get('duration')
        if dur:
            return float(dur)
        # Try from stream
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                dur = s.get('duration')
                if dur:
                    return float(dur)
    except Exception:
        pass
    return None

# ─── Short path for subtitle (Windows) ─────────────────────────────────────

def get_short_path(long_path):
    """Get Windows 8.3 short path to avoid special chars in FFmpeg filter."""
    try:
        if sys.platform == 'win32':
            # Use kernel32 GetShortPathNameW
            import ctypes
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, 512)
            short = buf.value
            if short and len(short) < len(long_path):
                return short
    except Exception:
        pass
    return long_path

# ─── EQ filter presets ─────────────────────────────────────────────────────

EQ_PRESETS = {
    '原始': '',
    '方案1-清晰': 'highpass=80,equalizer=f=3000:t=q:w=1:g=3,equalizer=f=5000:t=q:w=1:g=2,loudnorm=I=-16:TP=-1.5:LRA=11',
    '方案2-温暖': 'highpass=60,equalizer=f=200:t=q:w=1:g=2,equalizer=f=3000:t=q:w=1:g=1,loudnorm=I=-16:TP=-1.5:LRA=11',
    '方案3-去齿音': 'highpass=80,equalizer=f=6000:t=q:w=2:g=-4,equalizer=f=3000:t=q:w=1:g=2,loudnorm=I=-16:TP=-1.5:LRA=11',
    '方案4-会议室': 'highpass=100,equalizer=f=1000:t=q:w=1:g=3,equalizer=f=3000:t=q:w=1:g=4,compand=.01|.01:1|1:-90/-60|-60/-40|-40/-20|-20/0:0:0:0:0,loudnorm=I=-16:TP=-1.5:LRA=11',
}

# ─── Resolution presets ─────────────────────────────────────────────────────

RES_MAP = {
    '720p':  720,
    '1080p': 1080,
    '2K':    1440,
    '4K':    2160,
}

# ─── GUI ────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class VideoMergeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Video Merge Tool v4.0")
        self.root.geometry("960x820")
        self.root.resizable(True, True)
        
        # State
        self.work_dir = tk.StringVar()
        self.resolution = tk.StringVar(value='1080p')
        self.bitrate = tk.StringVar(value='8M')
        self.rc_mode = tk.StringVar(value='VBR (smart)')
        self.encoder = tk.StringVar(value='AMD GPU (hevc_amf)')
        self.parallel_count = tk.StringVar(value='4')
        self.eq_preset = tk.StringVar(value='原始')
        self.burn_sub = tk.BooleanVar(value=True)
        self.embed_sub = tk.BooleanVar(value=True)
        
        self.matched = []
        self.encoding = False
        self.stop_flag = False
        
        # FFmpeg paths
        try:
            self.ffmpeg_path = find_ffmpeg()
            self.ffprobe_path = find_ffprobe()
        except FileNotFoundError as e:
            messagebox.showerror("FFmpeg not found", str(e))
            sys.exit(1)
        
        self._build_ui()
    
    def _build_ui(self):
        # ── Top: directory + scan ──
        top = ttk.LabelFrame(self.root, text="Working Directory", padding=5)
        top.pack(fill='x', padx=8, pady=4)
        
        ttk.Entry(top, textvariable=self.work_dir, width=70).pack(side='left', padx=4)
        ttk.Button(top, text="Browse", command=self._browse).pack(side='left', padx=4)
        ttk.Button(top, text="Scan", command=self._scan, style='Accent.TButton').pack(side='left', padx=4)
        
        # ── Settings row ──
        settings = ttk.LabelFrame(self.root, text="Settings", padding=5)
        settings.pack(fill='x', padx=8, pady=4)
        
        row1 = ttk.Frame(settings)
        row1.pack(fill='x', pady=2)
        ttk.Label(row1, text="Resolution:").pack(side='left', padx=4)
        ttk.Combobox(row1, textvariable=self.resolution, values=list(RES_MAP.keys()), width=6, state='readonly').pack(side='left', padx=4)
        ttk.Label(row1, text="Bitrate:").pack(side='left', padx=4)
        ttk.Combobox(row1, textvariable=self.bitrate, values=['4M','6M','8M','10M','12M','15M','20M'], width=5, state='readonly').pack(side='left', padx=4)
        ttk.Label(row1, text="RC Mode:").pack(side='left', padx=4)
        ttk.Combobox(row1, textvariable=self.rc_mode, values=['VBR (smart)', 'CBR (fixed)', 'CQ (constant quality)'], width=16, state='readonly').pack(side='left', padx=4)
        ttk.Label(row1, text="Encoder:").pack(side='left', padx=4)
        ttk.Combobox(row1, textvariable=self.encoder, values=['AMD GPU (hevc_amf)', 'CPU (libx264)'], width=18, state='readonly').pack(side='left', padx=4)
        ttk.Label(row1, text="Parallel:").pack(side='left', padx=4)
        ttk.Combobox(row1, textvariable=self.parallel_count, values=['2','3','4','5','6'], width=3, state='readonly').pack(side='left', padx=4)
        
        row2 = ttk.Frame(settings)
        row2.pack(fill='x', pady=2)
        ttk.Label(row2, text="Voice EQ:").pack(side='left', padx=4)
        ttk.Combobox(row2, textvariable=self.eq_preset, values=list(EQ_PRESETS.keys()), width=14, state='readonly').pack(side='left', padx=4)
        ttk.Checkbutton(row2, text="Burn subtitles (hardsub)", variable=self.burn_sub).pack(side='left', padx=12)
        ttk.Checkbutton(row2, text="Embed subtitles (softsub)", variable=self.embed_sub).pack(side='left', padx=12)
        
        # ── Video list ──
        list_frame = ttk.LabelFrame(self.root, text="Video List (check to encode)", padding=5)
        list_frame.pack(fill='both', expand=True, padx=8, pady=4)
        
        cols = ('select', 'video', 'audio', 'sub', 'status')
        self.tree = ttk.Treeview(list_frame, columns=cols, show='headings', height=10)
        self.tree.heading('select', text='[X]')
        self.tree.heading('video', text='Video')
        self.tree.heading('audio', text='Audio')
        self.tree.heading('sub', text='Subtitle')
        self.tree.heading('status', text='Status')
        self.tree.column('select', width=40, anchor='center')
        self.tree.column('video', width=280)
        self.tree.column('audio', width=220)
        self.tree.column('sub', width=220)
        self.tree.column('status', width=80, anchor='center')
        
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        
        self.tree.bind('<Double-1>', self._toggle_select)
        
        btn_row = ttk.Frame(list_frame)
        btn_row.pack(fill='x', pady=2)
        ttk.Button(btn_row, text="Select All", command=self._select_all).pack(side='left', padx=4)
        ttk.Button(btn_row, text="Deselect All", command=self._deselect_all).pack(side='left', padx=4)
        
        # ── Progress ──
        prog_frame = ttk.LabelFrame(self.root, text="Progress", padding=5)
        prog_frame.pack(fill='x', padx=8, pady=4)
        
        ttk.Label(prog_frame, text="Overall:").pack(anchor='w')
        self.overall_bar = ttk.Progressbar(prog_frame, mode='determinate', length=900)
        self.overall_bar.pack(fill='x', pady=2)
        self.overall_label = ttk.Label(prog_frame, text="0 / 0")
        self.overall_label.pack(anchor='w')
        
        ttk.Label(prog_frame, text="Current:").pack(anchor='w')
        self.current_bar = ttk.Progressbar(prog_frame, mode='determinate', length=900)
        self.current_bar.pack(fill='x', pady=2)
        self.current_label = ttk.Label(prog_frame, text="Idle")
        self.current_label.pack(anchor='w')
        
        # ── Log ──
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        log_frame.pack(fill='both', expand=True, padx=8, pady=4)
        
        self.log_text = tk.Text(log_frame, height=6, wrap='word', state='disabled',
                                bg='#1e1e1e', fg='#d4d4d4', font=('Consolas', 9))
        log_sb = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        log_sb.pack(side='right', fill='y')
        
        # ── Action buttons ──
        action = ttk.Frame(self.root)
        action.pack(fill='x', padx=8, pady=6)
        self.start_btn = ttk.Button(action, text="START", command=self._start)
        self.start_btn.pack(side='left', padx=8)
        self.stop_btn = ttk.Button(action, text="STOP", command=self._stop, state='disabled')
        self.stop_btn.pack(side='left', padx=8)
        
        # FFmpeg info
        ttk.Label(action, text=f"FFmpeg: {self.ffmpeg_path}").pack(side='right', padx=8)
    
    # ── UI helpers ──
    
    def log(self, msg):
        """Thread-safe log."""
        self.root.after(0, self._log_ui, msg)
    
    def _log_ui(self, msg):
        self.log_text.config(state='normal')
        ts = time.strftime('%H:%M:%S')
        self.log_text.insert('end', f"[{ts}] {msg}\n")
        self.log_text.see('end')
        self.log_text.config(state='disabled')
    
    def _browse(self):
        d = filedialog.askdirectory(title="Select video directory")
        if d:
            self.work_dir.set(d)
    
    def _toggle_select(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if item and col == '#1':
            cur = self.tree.set(item, 'select')
            self.tree.set(item, 'select', '' if cur == 'Y' else 'Y')
    
    def _select_all(self):
        for item in self.tree.get_children():
            self.tree.set(item, 'select', 'Y')
    
    def _deselect_all(self):
        for item in self.tree.get_children():
            self.tree.set(item, 'select', '')
    
    # ── Scan ──
    
    def _scan(self):
        wdir = self.work_dir.get().strip()
        if not wdir or not os.path.isdir(wdir):
            messagebox.showwarning("Warning", "Please select a valid directory first!")
            return
        
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.matched = []
        
        # Collect files
        video_files = []
        audio_files = []
        sub_files = []
        
        for f in os.listdir(wdir):
            full = os.path.join(wdir, f)
            if not os.path.isfile(full):
                continue
            ext = Path(f).suffix.lower()
            if ext in VIDEO_EXT:
                video_files.append(f)
            elif ext in AUDIO_EXT and has_audio_tag(f):
                audio_files.append(f)
            elif ext in SUB_EXT and has_sub_tag(f):
                sub_files.append(f)
        
        if not video_files:
            messagebox.showinfo("Info", "No video files found in directory.")
            return
        
        video_files.sort()
        audio_files.sort()
        sub_files.sort()
        
        self.matched = match_files(video_files, audio_files, sub_files)
        
        for i, m in enumerate(self.matched):
            a_icon = '[OK]' if m['audio'] else '[--]'
            s_icon = '[OK]' if m['sub'] else '[--]'
            self.tree.insert('', 'end', iid=str(i), values=(
                'Y', m['video'], a_icon + ' ' + (m['audio'] or ''), s_icon + ' ' + (m['sub'] or ''), 'Ready'
            ))
        
        has_audio = sum(1 for m in self.matched if m['audio'])
        has_sub = sum(1 for m in self.matched if m['sub'])
        self.log(f"Scan done: {len(self.matched)} videos, {has_audio} audio matched, {has_sub} subs matched")
    
    # ── Encoding ──
    
    def _start(self):
        if self.encoding:
            return
        if not self.matched:
            messagebox.showwarning("Warning", "Please scan first!")
            return
        
        # Collect selected
        self.todo = []
        for item in self.tree.get_children():
            if self.tree.set(item, 'select') == 'Y':
                idx = int(item)
                self.todo.append(idx)
        
        if not self.todo:
            messagebox.showwarning("Warning", "No videos selected!")
            return
        
        # Check at least one has audio
        has_any_audio = any(self.matched[i]['audio'] for i in self.todo)
        if not has_any_audio:
            messagebox.showwarning("Warning", "No matched audio files found. Cannot encode without audio.")
            return
        
        self.encoding = True
        self.stop_flag = False
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        
        n_parallel = int(self.parallel_count.get())
        self.log(f"Starting encode: {len(self.todo)} videos, {n_parallel} parallel streams")
        
        # Run in background thread
        t = threading.Thread(target=self._encode_loop, args=(self.todo[:], n_parallel), daemon=True)
        t.start()
    
    def _stop(self):
        self.stop_flag = True
        self.log("STOP requested - waiting for current jobs to finish...")
    
    def _encode_loop(self, todo, n_parallel):
        total = len(todo)
        done = 0
        failed = 0
        
        self.root.after(0, self._update_overall, 0, total)
        
        def encode_one(idx):
            if self.stop_flag:
                return False, idx
            m = self.matched[idx]
            return self._encode_single(idx, m), idx
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_parallel) as executor:
            futures = {executor.submit(encode_one, idx): idx for idx in todo}
            
            for future in concurrent.futures.as_completed(futures):
                if self.stop_flag:
                    break
                success, idx = future.result()
                if success:
                    done += 1
                    self.root.after(0, self._update_tree_status, idx, 'Done')
                else:
                    failed += 1
                    self.root.after(0, self._update_tree_status, idx, 'FAIL')
                self.root.after(0, self._update_overall, done + failed, total)
        
        self.log(f"Encoding finished: {done} done, {failed} failed")
        self.root.after(0, self._encode_done)
    
    def _encode_single(self, idx, m):
        """Encode one video. Returns True on success."""
        wdir = self.work_dir.get().strip()
        video_path = os.path.join(wdir, m['video'])
        audio_path = os.path.join(wdir, m['audio']) if m['audio'] else None
        sub_path = os.path.join(wdir, m['sub']) if m['sub'] else None
        
        # Output path
        out_dir = os.path.join(wdir, '_video_out')
        os.makedirs(out_dir, exist_ok=True)
        vstem = Path(m['video']).stem
        res_label = self.resolution.get()
        out_path = os.path.join(out_dir, f"{vstem}_{res_label}.mp4")
        
        # If output exists and is > 1MB, skip
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 1024*1024:
            self.log(f"SKIP (already exists): {vstem}")
            return True
        
        self.log(f"Encoding: {vstem}")
        self.root.after(0, self._update_tree_status, idx, 'Encoding...')
        self.root.after(0, self._update_current, 0, f"Starting: {vstem}")
        
        # Get duration for progress
        duration = get_video_duration(video_path, self.ffprobe_path)
        if duration:
            self.log(f"  Duration: {duration:.1f}s")
        else:
            self.log(f"  Duration: unknown (will use time-based progress)")
        
        # Build FFmpeg command
        cmd = [self.ffmpeg_path, '-y', '-progress', 'pipe:1', '-nostats']
        
        # Hardware-accelerated decoding to offload CPU
        if 'AMD' in self.encoder.get() or 'hevc_amf' in self.encoder.get():
            cmd.extend(['-hwaccel', 'd3d11va'])
        
        # ALL inputs must come BEFORE any output options
        cmd.extend(['-i', video_path])
        if audio_path:
            cmd.extend(['-i', audio_path])
        
        # Embed subtitles as softsub - add as input BEFORE output options
        embed_sub_idx = None
        if self.embed_sub.get() and sub_path and os.path.isfile(sub_path):
            cmd.extend(['-i', sub_path])
            embed_sub_idx = 2 if audio_path else 1
        
        # Video filter
        res_h = RES_MAP.get(res_label, 1080)
        vf_parts = [f'scale=-2:{res_h}', f'pad=ceil(iw/2)*2:{res_h}']
        
        # Subtitle burning - use RELATIVE path since cwd=wdir
        if self.burn_sub.get() and sub_path and os.path.isfile(sub_path):
            # Use just the filename (relative to cwd=wdir)
            # This avoids ALL path encoding issues with Chinese/special chars
            sub_rel = m['sub']  # just the filename like "xxx_translated.srt"
            
            # Escape for FFmpeg subtitles filter: backslash->forward, colon->\:
            # But with relative path there are no drive letters, so just handle backslashes
            sub_esc = sub_rel.replace('\\', '/').replace(':', '\\:')
            
            font_size = max(res_h // 45, 12)
            style = (
                f"FontName=Microsoft YaHei,FontSize={font_size},"
                f"PrimaryColour=&H00FFFFFF,BackColour=&H00000000,"
                f"Outline=1,OutlineColour=&H00000000,Shadow=0,"
                f"BorderStyle=3,Alignment=2,MarginV=0"
            )
            vf_parts.append(f"subtitles='{sub_esc}':force_style='{style}'")
        
        vf_str = ','.join(vf_parts)
        
        # ALL output options below
        cmd.extend(['-vf', vf_str])
        cmd.extend(['-map', '0:v:0'])
        if audio_path:
            cmd.extend(['-map', '1:a:0'])
        
        # Encoder + Rate Control
        rc = self.rc_mode.get()
        if 'AMD' in self.encoder.get() or 'hevc_amf' in self.encoder.get():
            if rc == 'CQ (constant quality)':
                # CQ mode: constant quality, smallest files, best quality-per-bit
                cmd.extend(['-c:v', 'hevc_amf',
                            '-rc', 'cqp', '-qp_i', '26', '-qp_p', '28', '-qp_b', '30',
                            '-quality', 'speed', '-usage', 'transcoding',
                            '-threads', '2'])
            elif rc == 'VBR (smart)':
                # VBR: target bitrate as average, peaks allowed, best size/quality tradeoff
                cmd.extend(['-c:v', 'hevc_amf',
                            '-rc', 'vbr_peak', '-b:v', self.bitrate.get(),
                            '-maxrate', str(int(self.bitrate.get().rstrip('M')) * 2) + 'M',
                            '-quality', 'speed', '-usage', 'transcoding',
                            '-threads', '2'])
            else:
                # CBR: fixed bitrate, largest files
                cmd.extend(['-c:v', 'hevc_amf', '-b:v', self.bitrate.get(),
                            '-quality', 'speed', '-usage', 'transcoding', '-rc', 'cbr',
                            '-threads', '2'])
        else:
            if rc == 'CQ (constant quality)':
                cmd.extend(['-c:v', 'libx265', '-crf', '26', '-preset', 'fast',
                            '-threads', '2'])
            elif rc == 'VBR (smart)':
                cmd.extend(['-c:v', 'libx265', '-b:v', self.bitrate.get(),
                            '-maxrate', str(int(self.bitrate.get().rstrip('M')) * 2) + 'M',
                            '-preset', 'fast',
                            '-threads', '2'])
            else:
                cmd.extend(['-c:v', 'libx264', '-b:v', self.bitrate.get(),
                            '-preset', 'fast', '-crf', '23',
                            '-threads', '2'])
        
        # Audio
        eq_filter = EQ_PRESETS.get(self.eq_preset.get(), '')
        if eq_filter and audio_path:
            cmd.extend(['-c:a', 'aac', '-b:a', '192k', '-af', eq_filter])
        else:
            cmd.extend(['-c:a', 'copy'])
        
        # Embed subtitle mapping
        if embed_sub_idx is not None:
            cmd.extend(['-map', f'{embed_sub_idx}:s:0', '-c:s', 'mov_text'])
        
        cmd.append(out_path)
        
        self.log(f"  CMD: {' '.join(cmd[:8])}...")
        
        # Run FFmpeg - redirect stderr to a pipe we read AFTER process ends
        # Using PIPE for stderr can cause deadlock if buffer fills up,
        # so we use DEVNULL for real-time and capture errors from temp file
        import tempfile
        err_tmp = os.path.join(out_dir, f"_ffmpeg_err_{vstem}.log")
        
        try:
            with open(err_tmp, 'w', encoding='utf-8', errors='replace') as err_f:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=err_f,
                    encoding='utf-8', errors='replace',
                    cwd=wdir,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
        except Exception as e:
            self.log(f"  ERROR starting FFmpeg: {e}")
            return False
        
        # Parse progress
        start_time = time.time()
        last_report = 0
        
        while True:
            if self.stop_flag:
                proc.kill()
                self.log(f"  STOPPED: {vstem}")
                return False
            
            line = proc.stdout.readline()
            if not line:
                # Check if process ended
                if proc.poll() is not None:
                    break
                continue
            
            line = line.strip()
            if line.startswith('out_time_ms='):
                try:
                    us = int(line.split('=')[1])
                    cur_s = us / 1_000_000
                    if duration and duration > 0:
                        pct = min(cur_s / duration * 100, 100)
                        self.root.after(0, self._update_current, pct,
                                        f"{vstem}: {cur_s:.0f}s / {duration:.0f}s ({pct:.0f}%)")
                    else:
                        # Fallback: time-based progress estimate
                        elapsed = time.time() - start_time
                        est_total = elapsed / max(cur_s, 1) * max(cur_s, 1) * 1.1  # rough
                        if elapsed > 2 and cur_s > 0:
                            speed = cur_s / elapsed
                            pct = min(cur_s / (cur_s + speed * 5) * 100, 95)
                            self.root.after(0, self._update_current, pct,
                                            f"{vstem}: {cur_s:.0f}s (speed={speed:.1f}x)")
                except (ValueError, ZeroDivisionError):
                    pass
        
        # Wait for process to finish
        proc.wait()
        
        # Read error log
        stderr_out = ''
        try:
            with open(err_tmp, 'r', encoding='utf-8', errors='replace') as f:
                stderr_out = f.read()
            os.remove(err_tmp)
        except:
            pass
        
        if proc.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 1024:
            size_mb = os.path.getsize(out_path) / (1024*1024)
            self.log(f"  DONE: {vstem} -> {size_mb:.1f}MB")
            self.root.after(0, self._update_current, 100, f"Done: {vstem}")
            return True
        else:
            self.log(f"  FAIL: {vstem} (returncode={proc.returncode})")
            # Log last few lines of stderr for debugging
            if stderr_out:
                err_lines = stderr_out.strip().split('\n')[-5:]
                for el in err_lines:
                    self.log(f"    {el.strip()}")
            # Remove partial output
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except:
                    pass
            return False
    
    # ── UI updates (called from main thread via after) ──
    
    def _update_tree_status(self, idx, status):
        try:
            self.tree.set(str(idx), 'status', status)
        except:
            pass
    
    def _update_overall(self, done, total):
        self.overall_bar['value'] = (done / max(total, 1)) * 100
        self.overall_label.config(text=f"{done} / {total}")
    
    def _update_current(self, pct, text):
        self.current_bar['value'] = pct
        self.current_label.config(text=text)
    
    def _encode_done(self):
        self.encoding = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.current_label.config(text="All done!")


# ─── Main ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', 1.25)
    except:
        pass
    app = VideoMergeApp(root)
    root.mainloop()
