import os
from PyQt6.QtMultimedia import QSoundEffect
from PyQt6.QtCore import QUrl, QObject

class SoundPlayer(QObject):
    """Utility class for playing sounds in the application."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._beep_effect = QSoundEffect(self)
        # Using a standard system beep sound if possible, or a local file
        # For now, we'll try to find a common wav file or just use a placeholder
        # Most Windows systems have this:
        beep_path = "C:/Windows/Media/chimes.wav"
        if os.path.exists(beep_path):
            self._beep_effect.setSource(QUrl.fromLocalFile(beep_path))
        self._beep_effect.setVolume(0.5)

    def play_beep(self):
        """Play a standard beep sound."""
        if self._beep_effect.status() == QSoundEffect.Status.Ready:
            self._beep_effect.play()
        else:
            # Fallback to winsound if QSoundEffect isn't ready
            try:
                import winsound
                winsound.MessageBeep()
            except ImportError:
                print("\a", end='')

    def play_wav(self, file_path):
        """Play a custom wav file."""
        if os.path.exists(file_path):
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(file_path))
            effect.play()

    def stop_all(self):
        """Stop all currently playing sounds."""
        self._beep_effect.stop()

