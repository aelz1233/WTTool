"""Short local warning tones with user-controlled volume."""
import math
from pathlib import Path
import struct
import wave

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect


class WarningAudio:
    def __init__(self, directory, parent):
        self.effects = {}
        folder = Path(directory) / "sounds"
        folder.mkdir(parents=True, exist_ok=True)
        self.default_paths = {}
        for key, frequency, pulses in (("speed", 880, 2), ("g", 620, 3), ("fuel", 440, 1), ("stall", 1040, 4)):
            # Versioned filenames replace older, very quiet tones without touching user files.
            path = folder / (key + "_v2.wav")
            if not path.exists():
                samples = []
                rate = 22050
                for _ in range(pulses):
                    count = int(rate * .14)
                    for i in range(count):
                        envelope = min(1, i / 220, (count - i) / 220)
                        samples.append(int(28000 * envelope * math.sin(2 * math.pi * frequency * i / rate)))
                    samples.extend([0] * int(rate * .06))
                with wave.open(str(path), "wb") as output:
                    output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                    output.writeframes(struct.pack("<" + "h" * len(samples), *samples))
            effect = QSoundEffect(parent)
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setLoopCount(1)
            self.effects[key] = effect
            self.default_paths[key] = path

    def set_source(self, key, path):
        path = Path(path)
        if key not in self.effects or not path.is_file():
            return False
        effect = self.effects[key]
        effect.stop()
        effect.setSource(QUrl.fromLocalFile(str(path)))
        return True

    def reset_source(self, key):
        return self.set_source(key, self.default_paths[key])

    def play(self, key, volume, force=False):
        if volume <= 0 or any(effect.isPlaying() for effect in self.effects.values()):
            return False
        effect = self.effects[key]
        if not effect.isLoaded():
            return False
        effect.setVolume(max(0, min(1, volume)))
        effect.play()
        return True

    def stop(self):
        for effect in self.effects.values():
            effect.stop()
