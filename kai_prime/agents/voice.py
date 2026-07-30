"""Voice agent — TTS with mood mapping, multi-backend. STT via faster-whisper/Vosk."""
from __future__ import annotations
import os, re, subprocess, sys, tempfile, threading, platform, shutil, importlib.util


class VoiceAgent:
    """Multi-backend TTS with 14-mood voice modulation. STT via faster-whisper or Vosk."""

    MOOD_PROFILES = {
        "happy":      {"rate_mod": 10,  "pitch_mod": 3,  "amp_mod": 8},
        "excited":    {"rate_mod": 18,  "pitch_mod": 6,  "amp_mod": 12},
        "sad":        {"rate_mod": -18, "pitch_mod": -4, "amp_mod": -8},
        "worried":    {"rate_mod": -5,  "pitch_mod": 0,  "amp_mod": 0},
        "tired":      {"rate_mod": -22, "pitch_mod": -6, "amp_mod": -12},
        "sleepy":     {"rate_mod": -28, "pitch_mod": -8, "amp_mod": -18},
        "curious":    {"rate_mod": 8,   "pitch_mod": 2,  "amp_mod": 4},
        "proud":      {"rate_mod": 3,   "pitch_mod": 1,  "amp_mod": 8},
        "anxious":    {"rate_mod": 12,  "pitch_mod": 4,  "amp_mod": 4},
        "neutral":    {"rate_mod": 0,   "pitch_mod": 0,  "amp_mod": 0},
        "confident":  {"rate_mod": -3,  "pitch_mod": -1, "amp_mod": 5},
        "friendly":   {"rate_mod": 5,   "pitch_mod": 2,  "amp_mod": 6},
        "empathetic": {"rate_mod": -10, "pitch_mod": -2, "amp_mod": -3},
        "urgent":     {"rate_mod": 20,  "pitch_mod": 5,  "amp_mod": 10},
    }

    def __init__(self, voice: str = "", rate: int = 155):
        self.voice = voice or "en-US-ChristopherNeural"
        self.base_rate = rate
        self.rate = rate
        self._pitch_mod = 0
        self._amp_mod = 0
        self._current_mood = "neutral"
        self._backend = self._detect_backend()
        self._speaking = False
        self._stt_backend = None
        self._stt_model = None

    def set_mood(self, mood: str):
        profile = self.MOOD_PROFILES.get(mood, self.MOOD_PROFILES["neutral"])
        self.rate = max(80, min(250, self.base_rate + profile["rate_mod"]))
        self._pitch_mod = profile["pitch_mod"]
        self._amp_mod = profile["amp_mod"]
        self._current_mood = mood

    def _detect_backend(self) -> str:
        if importlib.util.find_spec("edge_tts"):
            return "edge-tts"
        if platform.system() == "Windows":
            return "sapi"
        if shutil.which("espeak-ng"):
            return "espeak-ng"
        if shutil.which("espeak"):
            return "espeak"
        if platform.system() == "Darwin" and shutil.which("say"):
            return "say"
        return "none"

    @property
    def available(self) -> bool:
        return self._backend != "none"

    def speak(self, text: str, blocking: bool = False) -> bool:
        if not self.available or not text.strip():
            return False
        clean = self._clean_for_tts(text)
        if not clean.strip():
            return False
        if blocking:
            return self._run_tts(clean)
        threading.Thread(target=self._run_tts, args=(clean,), daemon=True).start()
        return True

    def _run_tts(self, text: str) -> bool:
        if self._speaking:
            return False
        self._speaking = True
        try:
            if self._backend == "edge-tts":
                return self._edge_tts(text)
            elif self._backend == "sapi":
                return self._sapi(text)
            elif self._backend in ("espeak-ng", "espeak"):
                return self._espeak(text)
            elif self._backend == "say":
                return self._mac_say(text)
            return False
        except Exception:
            return False
        finally:
            self._speaking = False

    def _edge_tts(self, text: str) -> bool:
        temp_mp3 = os.path.join(tempfile.gettempdir(), f"kai_tts_{os.getpid()}_{threading.get_ident()}.mp3")
        rate_str = f"+{self.rate - 150}Hz" if self.rate > 150 else f"{self.rate - 150}Hz"
        pitch_str = f"+{self._pitch_mod * 2}Hz" if self._pitch_mod > 0 else f"{self._pitch_mod * 2}Hz"
        try:
            subprocess.run([
                sys.executable, "-m", "edge_tts",
                "--voice", self.voice, "--text", text,
                "--rate", rate_str, "--pitch", pitch_str,
                "--write-media", temp_mp3,
            ], timeout=45, capture_output=True)
            if not os.path.exists(temp_mp3):
                return False
            if platform.system() == "Windows":
                media_path = temp_mp3.replace("\\", "\\\\")
                subprocess.run(["powershell", "-Command",
                    "Add-Type -AssemblyName presentationCore; "
                    f"$player = New-Object System.Windows.Media.MediaPlayer; "
                    f"$player.Open([Uri]'file:///{media_path}'); "
                    "while (-not $player.NaturalDuration.HasTimeSpan) { Start-Sleep -Milliseconds 100 }; "
                    "$player.Volume = 1.0; $player.Play(); "
                    "$duration = [Math]::Min(18000, [Math]::Max(1200, [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds + 250)); "
                    "Start-Sleep -Milliseconds $duration; $player.Stop(); $player.Close();"
                ], timeout=30, capture_output=True)
                return True
            return False
        except Exception:
            return False

    def _sapi(self, text: str) -> bool:
        escaped = text.replace("'", "''")
        cmd = ["powershell", "-Command",
            f"Add-Type -AssemblyName System.Speech; "
            f"$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$synth.Rate = {max(-10, min(10, (self.rate - 150) // 15))}; "
            f"$synth.Speak('{escaped}')"]
        try:
            subprocess.run(cmd, timeout=30, capture_output=True)
            return True
        except Exception:
            return False

    def _espeak(self, text: str) -> bool:
        pitch = 50 + self._pitch_mod
        amp = 120 + self._amp_mod
        try:
            subprocess.run([self._backend, "-s", str(self.rate), "-p", str(pitch), "-a", str(amp), text],
                           timeout=30, capture_output=True)
            return True
        except Exception:
            return False

    def _mac_say(self, text: str) -> bool:
        try:
            subprocess.run(["say", "-r", str(self.rate), text], timeout=30, capture_output=True)
            return True
        except Exception:
            return False

    def stop(self):
        self._speaking = False

    def toggle(self) -> bool:
        self._backend = "none" if self._backend != "none" else self._detect_backend()
        return self._backend != "none"

    def list_voices(self) -> list[str]:
        if self._backend != "edge-tts":
            return ["edge-tts not installed"]
        try:
            r = subprocess.run([sys.executable, "-m", "edge_tts", "--list-voices"],
                               capture_output=True, text=True, timeout=15)
            return [l.split(":", 1)[1].strip() for l in r.stdout.splitlines()
                    if l.startswith("Name:") and "en-" in l][:30]
        except Exception:
            return ["Failed to list voices"]

    def _clean_for_tts(self, text: str) -> str:
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`[^`]+`', '', text)
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'[🦊🐾💬🎤✋🔊🔇]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        sentences = text.split('. ')
        if len(sentences) > 2:
            text = '. '.join(sentences[:2]) + '.'
        if len(text) > 200:
            text = text[:197] + '...'
        return text

    # ── STT ──────────────────────────────────────────────────────────────────

    def init_stt(self, backend: str = "auto", model_size: str = "small") -> str:
        if backend == "auto":
            if importlib.util.find_spec("faster_whisper"):
                backend = "faster-whisper"
            elif importlib.util.find_spec("vosk"):
                backend = "vosk"
            else:
                return "no STT backend available (install faster-whisper or vosk)"
        if backend == "faster-whisper":
            try:
                from faster_whisper import WhisperModel
                self._stt_model = WhisperModel(model_size, device="cpu", compute_type="int8")
                self._stt_backend = "faster-whisper"
                return f"STT ready: faster-whisper ({model_size})"
            except Exception as e:
                return f"faster-whisper init failed: {e}"
        elif backend == "vosk":
            try:
                import vosk, json as vosk_json
                model_path = os.environ.get("VOSK_MODEL", "vosk-model-small-en-us-0.15")
                self._stt_model = vosk.KaldiRecognizer(vosk.Model(model_path), 16000)
                self._stt_backend = "vosk"
                return "STT ready: vosk"
            except Exception as e:
                return f"vosk init failed: {e}"
        return f"unknown STT backend: {backend}"

    @property
    def stt_available(self) -> bool:
        return self._stt_backend is not None

    def transcribe_file(self, path: str) -> str:
        if not self.stt_available:
            return ""
        if self._stt_backend == "faster-whisper":
            try:
                segments, _ = self._stt_model.transcribe(path, beam_size=5)
                return " ".join(s.text.strip() for s in segments)
            except Exception:
                return ""
        elif self._stt_backend == "vosk":
            try:
                import wave
                with wave.open(path, "rb") as wf:
                    data = wf.readframes(wf.getnframes())
                if self._stt_model.AcceptWaveform(data):
                    import json
                    return json.loads(self._stt_model.Result()).get("text", "")
                import json
                return json.loads(self._stt_model.FinalResult()).get("text", "")
            except Exception:
                return ""
        return ""

    def listen(self, duration: float = 5.0) -> str:
        if not self.stt_available:
            return ""
        try:
            import sounddevice as sd
            import numpy as np
            sr = 16000
            audio = sd.rec(int(duration * sr), samplerate=sr, channels=1, dtype="int16")
            sd.wait()
            tmp_wav = os.path.join(tempfile.gettempdir(), f"kai_stt_{os.getpid()}.wav")
            import wave
            with wave.open(tmp_wav, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(audio.tobytes())
            result = self.transcribe_file(tmp_wav)
            try:
                os.remove(tmp_wav)
            except Exception:
                pass
            return result
        except Exception:
            return ""
