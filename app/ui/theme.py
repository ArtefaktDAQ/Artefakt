"""
Artefakt DAQ - Zentrales Theming System

Dieses Modul definiert alle Farben, Styles und UI-Konstanten für die Anwendung.
Verwende diese Definitionen statt hardcodierter Farbwerte im Code.

WICHTIG: Dynamische Status-Signalisierung (grüne/rote Borders etc.) wird über
die get_*_style() Funktionen bereitgestellt, um Konsistenz zu gewährleisten.
"""

from PyQt6.QtWidgets import QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor, QFont
from dataclasses import dataclass
from typing import Literal


# =============================================================================
# FARBPALETTE
# =============================================================================

@dataclass(frozen=True)
class Colors:
    """Zentrale Farbdefinitionen für die Anwendung"""
    
    # -------------------------------------------------------------------------
    # Primärfarben (Lila/Violet - Markenfarbe)
    # -------------------------------------------------------------------------
    PRIMARY = "#6C5CE7"
    PRIMARY_DARK = "#5541D7"
    PRIMARY_LIGHT = "#A29BFE"
    PRIMARY_SUBTLE = "rgba(108, 92, 231, 0.15)"
    
    # -------------------------------------------------------------------------
    # Hintergrundfarben (Dunkel-Theme)
    # -------------------------------------------------------------------------
    BG_DARK = "#0F0F1A"           # Haupthintergrund / Fenster
    BG_CARD = "#141424"           # Karten, Panels, GroupBoxes
    BG_ELEVATED = "#1A1A2E"       # Erhöhte Elemente, Hover-States
    BG_INPUT = "#2D2D44"          # Input-Felder, Dropdowns
    BG_SIDEBAR = "#1A022A"        # Sidebar-Basis
    
    # -------------------------------------------------------------------------
    # Status-Farben (WICHTIG: Werden für Signalisierung verwendet!)
    # -------------------------------------------------------------------------
    # Erfolg / Verbunden / Aktiv
    SUCCESS = "#4CAF50"           # Standard-Grün
    SUCCESS_BRIGHT = "#00D26A"    # Helleres Grün für Akzente
    SUCCESS_DARK = "#3D8B40"      # Dunkleres Grün für Hover
    SUCCESS_TEXT = "#2ECC40"      # Textfarbe Grün
    
    # Warnung / Teilweise / Pending
    WARNING = "#FFA500"           # Orange
    WARNING_BRIGHT = "#FFC107"    # Helles Orange/Gelb
    WARNING_DARK = "#E5AC00"      # Dunkleres Orange
    
    # Fehler / Nicht verbunden / Inaktiv
    ERROR = "#F44336"             # Standard-Rot
    ERROR_BRIGHT = "#FF4757"      # Helleres Rot
    ERROR_DARK = "#D32F2F"        # Dunkleres Rot
    ERROR_TEXT = "#FF4136"        # Textfarbe Rot
    
    # Info / Neutral
    INFO = "#2196F3"              # Blau
    INFO_BRIGHT = "#00B4D8"       # Cyan
    INFO_DARK = "#1565C0"         # Dunkelblau
    
    # -------------------------------------------------------------------------
    # Textfarben
    # -------------------------------------------------------------------------
    TEXT_PRIMARY = "#FFFFFF"
    TEXT_SECONDARY = "#A0A0B0"
    TEXT_MUTED = "#666677"
    TEXT_DISABLED = "#404050"
    
    # -------------------------------------------------------------------------
    # Rahmen und Trennlinien
    # -------------------------------------------------------------------------
    BORDER_DEFAULT = "rgba(255, 255, 255, 0.08)"
    BORDER_SUBTLE = "rgba(255, 255, 255, 0.05)"
    BORDER_HOVER = "rgba(255, 255, 255, 0.15)"
    
    # -------------------------------------------------------------------------
    # Grafik-/Graph-Farben
    # -------------------------------------------------------------------------
    GRAPH_BG = "#2D2D2D"
    GRAPH_GRID = "#404050"
    GRAPH_AXIS = "#BBBBBB"
    GRAPH_TEXT = "#EEEEEE"


# Instanz für einfachen Zugriff
COLORS = Colors()


# =============================================================================
# SIDEBAR THEME
# =============================================================================

class SidebarTheme:
    """Styles für die Sidebar - Glassmorphism Design"""
    
    WIDTH = 250
    COLLAPSED_WIDTH = 70
    
    # Hauptcontainer mit Glassmorphism-Effekt
    # Dunkler Gradient passend zum dunklen Theme (wie Graphs Tab)
    CONTAINER = f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(15, 15, 26, 0.98),
                stop:0.15 rgba(20, 18, 32, 0.96),
                stop:0.5 rgba(18, 18, 30, 0.94),
                stop:0.85 rgba(17, 17, 28, 0.96),
                stop:1 rgba(15, 15, 26, 0.98));
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }}
        QLabel {{
            border: none;
            background: transparent;
        }}
    """
    
    # Navigationsbuttons - Modern mit Hover-Animationen und Akzent-Indicator
    NAV_BUTTON = f"""
        QToolButton {{
            text-align: center;
            padding: 10px 8px 10px 12px;
            font-size: 12px;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.65);
            background: transparent;
            border: none;
            border-left: 3px solid transparent;
            border-radius: 0px 8px 8px 0px;
            margin: 2px 10px 2px 0px;
        }}
        QToolButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(168, 85, 247, 0.15),
                stop:1 rgba(168, 85, 247, 0.05));
            color: rgba(255, 255, 255, 0.95);
            border-left: 3px solid rgba(168, 85, 247, 0.5);
        }}
        QToolButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(168, 85, 247, 0.25),
                stop:1 rgba(168, 85, 247, 0.1));
            border-left: 3px solid rgba(168, 85, 247, 0.7);
        }}
        QToolButton:checked {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(168, 85, 247, 0.25),
                stop:0.7 rgba(168, 85, 247, 0.1),
                stop:1 transparent);
            color: {COLORS.TEXT_PRIMARY};
            border-left: 3px solid #A855F7;
            font-weight: 600;
        }}
        QToolButton:checked:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(168, 85, 247, 0.3),
                stop:0.7 rgba(168, 85, 247, 0.15),
                stop:1 transparent);
            border-left: 3px solid #C084FC;
        }}
    """
    
    # Alternative: Minimalistischer Nav-Style ohne Linken Rahmen
    NAV_BUTTON_MINIMAL = f"""
        QToolButton {{
            text-align: center;
            padding: 12px 16px;
            font-size: 12px;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.6);
            background: transparent;
            border: none;
            border-radius: 8px;
            margin: 3px 12px;
        }}
        QToolButton:hover {{
            background: rgba(168, 85, 247, 0.12);
            color: rgba(255, 255, 255, 0.9);
        }}
        QToolButton:pressed {{
            background: rgba(168, 85, 247, 0.2);
        }}
        QToolButton:checked {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(168, 85, 247, 0.3),
                stop:1 rgba(108, 92, 231, 0.2));
            color: {COLORS.TEXT_PRIMARY};
            font-weight: 600;
        }}
    """
    
    # Pill-Style Navigation (für kompakte Sidebars)
    NAV_BUTTON_PILL = f"""
        QToolButton {{
            text-align: center;
            padding: 10px 20px;
            font-size: 12px;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.65);
            background: transparent;
            border: 1px solid transparent;
            border-radius: 20px;
            margin: 4px 15px;
        }}
        QToolButton:hover {{
            background: rgba(168, 85, 247, 0.1);
            border: 1px solid rgba(168, 85, 247, 0.3);
            color: rgba(255, 255, 255, 0.9);
        }}
        QToolButton:pressed {{
            background: rgba(168, 85, 247, 0.2);
            border: 1px solid rgba(168, 85, 247, 0.5);
        }}
        QToolButton:checked {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(168, 85, 247, 0.4),
                stop:1 rgba(108, 92, 231, 0.3));
            border: 1px solid rgba(168, 85, 247, 0.5);
            color: {COLORS.TEXT_PRIMARY};
            font-weight: 600;
        }}
    """
    
    # Separator-Linien - subtiler
    SEPARATOR = """
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 transparent, stop:0.2 rgba(255, 255, 255, 0.1),
            stop:0.8 rgba(255, 255, 255, 0.1), stop:1 transparent);
        margin: 12px 25px;
        max-height: 1px;
    """
    
    # Programm-Name - klar und lesbar
    TITLE = f"""
        font-size: 24px;
        font-weight: 700;
        color: {COLORS.TEXT_PRIMARY};
        background: transparent;
    """
    
    # Version Text - heller für bessere Lesbarkeit
    VERSION = f"""
        font-size: 14px;
        font-weight: 500;
        color: rgba(100, 200, 255, 0.95);
        background: transparent;
    """
    
    # Project Status Container - minimal, no visible box
    STATUS_CONTAINER = """
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px 15px;
    """
    
    # Status Label
    STATUS_LABEL = f"""
        font-size: 12px;
        font-weight: 600;
        color: rgba(255, 255, 255, 0.7);
        background: transparent;
        padding-bottom: 2px;
    """


# =============================================================================
# NAVIGATION STYLES
# =============================================================================

class NavigationStyles:
    """
    Erweiterte Navigation-Styles für verschiedene Kontexte.
    
    Verwendung:
        # Hauptnavigation (Sidebar)
        btn.setStyleSheet(NavigationStyles.sidebar_button())
        
        # Tab-Navigation
        tab.setStyleSheet(NavigationStyles.tab_bar())
        
        # Breadcrumb-Navigation
        NavigationStyles.breadcrumb()
    """
    
    @staticmethod
    def sidebar_button(style: str = "default") -> str:
        """
        Sidebar-Navigationsbuttons mit verschiedenen Stilen.
        
        Args:
            style: "default", "minimal", "pill", "glow"
        """
        styles = {
            "default": SidebarTheme.NAV_BUTTON,
            "minimal": SidebarTheme.NAV_BUTTON_MINIMAL,
            "pill": SidebarTheme.NAV_BUTTON_PILL,
        }
        
        if style == "glow":
            return f"""
                QToolButton {{
                    text-align: center;
                    padding: 12px 16px;
                    font-size: 12px;
                    font-weight: 500;
                    color: rgba(255, 255, 255, 0.6);
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    margin: 3px 12px;
                }}
                QToolButton:hover {{
                    background: rgba(168, 85, 247, 0.15);
                    color: rgba(255, 255, 255, 0.95);
                }}
                QToolButton:checked {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba(168, 85, 247, 0.35),
                        stop:0.5 rgba(168, 85, 247, 0.2),
                        stop:1 rgba(168, 85, 247, 0.1));
                    color: {COLORS.TEXT_PRIMARY};
                    font-weight: 600;
                }}
            """
        
        return styles.get(style, styles["default"])
    
    @staticmethod
    def tab_bar() -> str:
        """Moderner Tab-Bar Style für horizontale Navigation"""
        return f"""
            QTabBar::tab {{
                background: transparent;
                color: {COLORS.TEXT_SECONDARY};
                padding: 12px 24px;
                margin-right: 4px;
                border: none;
                border-bottom: 2px solid transparent;
                font-weight: 500;
                font-size: 13px;
            }}
            QTabBar::tab:hover {{
                color: {COLORS.TEXT_PRIMARY};
                border-bottom: 2px solid rgba(168, 85, 247, 0.3);
            }}
            QTabBar::tab:selected {{
                color: {COLORS.TEXT_PRIMARY};
                border-bottom: 2px solid {COLORS.PRIMARY};
                font-weight: 600;
            }}
            QTabWidget::pane {{
                border: none;
                background: transparent;
            }}
        """
    
    @staticmethod
    def breadcrumb() -> str:
        """Breadcrumb-Navigation Style"""
        return f"""
            QLabel {{
                color: {COLORS.TEXT_SECONDARY};
                font-size: 12px;
                padding: 4px 8px;
            }}
            QLabel:hover {{
                color: {COLORS.PRIMARY};
            }}
            QPushButton {{
                background: transparent;
                color: {COLORS.TEXT_SECONDARY};
                border: none;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {COLORS.PRIMARY};
            }}
            QPushButton:last {{
                color: {COLORS.TEXT_PRIMARY};
                font-weight: 500;
            }}
        """
    
    @staticmethod
    def icon_nav(size: int = 40) -> str:
        """
        Icon-basierte Navigation (nur Icons, keine Text-Labels).
        Ideal für kompakte Toolbars.
        
        Args:
            size: Größe der Icons in Pixel
        """
        return f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: {size // 4}px;
                padding: {size // 8}px;
                margin: 2px;
                min-width: {size}px;
                min-height: {size}px;
                max-width: {size}px;
                max-height: {size}px;
            }}
            QToolButton:hover {{
                background: rgba(168, 85, 247, 0.15);
            }}
            QToolButton:pressed {{
                background: rgba(168, 85, 247, 0.25);
            }}
            QToolButton:checked {{
                background: rgba(168, 85, 247, 0.2);
                border: 1px solid rgba(168, 85, 247, 0.4);
            }}
        """
    
    @staticmethod
    def menu_item() -> str:
        """Dropdown-Menü Item Style"""
        return f"""
            QMenu {{
                background-color: {COLORS.BG_ELEVATED};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                background: transparent;
                color: {COLORS.TEXT_PRIMARY};
                padding: 10px 20px 10px 12px;
                border-radius: 6px;
                margin: 2px 4px;
            }}
            QMenu::item:hover {{
                background: rgba(168, 85, 247, 0.15);
            }}
            QMenu::item:selected {{
                background: rgba(168, 85, 247, 0.2);
            }}
            QMenu::separator {{
                height: 1px;
                background: {COLORS.BORDER_DEFAULT};
                margin: 6px 10px;
            }}
        """


# =============================================================================
# BUTTON STYLES
# =============================================================================

class ButtonStyles:
    """
    Zentrale Button-Styles für konsistentes UI-Design.
    
    Verwendung:
        # Einfacher Zugriff über get()
        btn.setStyleSheet(ButtonStyles.get("success"))
        btn.setStyleSheet(ButtonStyles.get("danger", size="large"))
        
        # Oder direkte Methoden
        btn.setStyleSheet(ButtonStyles.success())
        btn.setStyleSheet(ButtonStyles.primary())
    """
    
    # Größen-Konfiguration
    _SIZES = {
        "small": {"padding": "4px 10px", "font_size": "11px", "border_radius": "4px"},
        "medium": {"padding": "8px 16px", "font_size": "13px", "border_radius": "6px"},
        "large": {"padding": "12px 24px", "font_size": "15px", "border_radius": "10px"},
        "xlarge": {"padding": "16px 32px", "font_size": "17px", "border_radius": "12px"},
    }
    
    @staticmethod
    def get(variant: str = "primary", size: str = "medium") -> str:
        """
        Universelle Button-Style Funktion.
        
        Args:
            variant: "primary", "success", "danger", "warning", "secondary", "ghost"
            size: "small", "medium", "large", "xlarge"
        
        Returns:
            CSS-Stylesheet für QPushButton
        
        Beispiel:
            btn.setStyleSheet(ButtonStyles.get("success", "large"))
        """
        variants = {
            "primary": ButtonStyles.primary,
            "default": ButtonStyles.primary,
            "success": ButtonStyles.success,
            "danger": ButtonStyles.danger,
            "warning": ButtonStyles.warning,
            "secondary": ButtonStyles.secondary,
            "ghost": ButtonStyles.ghost,
            "icon": ButtonStyles.icon_button,
        }
        
        style_func = variants.get(variant, ButtonStyles.primary)
        
        # Ghost und icon haben eigene Größen-Logik
        if variant in ("ghost", "icon"):
            return style_func()
        
        return style_func(size)
    
    @staticmethod
    def primary(size: str = "medium") -> str:
        """Primärer Aktions-Button (Lila)"""
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["medium"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS.PRIMARY_LIGHT}, stop:1 {COLORS.PRIMARY});
                color: white;
                border: none;
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 600;
                font-size: {s['font_size']};
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS.PRIMARY}, stop:1 {COLORS.PRIMARY_DARK});
            }}
            QPushButton:pressed {{
                background: {COLORS.PRIMARY_DARK};
            }}
            QPushButton:disabled {{
                background: {COLORS.TEXT_DISABLED};
                color: {COLORS.TEXT_MUTED};
            }}
        """
    
    @staticmethod
    def success(size: str = "large") -> str:
        """Erfolgs-/Start-Button (Grün) - Modern mit Gradient"""
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["large"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34D399, stop:0.5 #10B981, stop:1 #059669);
                color: white;
                border: none;
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 700;
                font-size: {s['font_size']};
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4ADE80, stop:0.5 #22C55E, stop:1 #16A34A);
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #22C55E, stop:1 #15803D);
            }}
            QPushButton:disabled {{
                background: #374151;
                color: #6B7280;
            }}
        """
    
    @staticmethod
    def danger(size: str = "large") -> str:
        """Stopp-/Abbruch-Button (Rot) - Modern mit Gradient"""
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["large"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FB7185, stop:0.5 #F43F5E, stop:1 #E11D48);
                color: white;
                border: none;
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 700;
                font-size: {s['font_size']};
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FDA4AF, stop:0.5 #FB7185, stop:1 #F43F5E);
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F43F5E, stop:1 #BE123C);
            }}
            QPushButton:disabled {{
                background: #374151;
                color: #6B7280;
            }}
        """
    
    @staticmethod
    def warning(size: str = "medium") -> str:
        """Warnung-Button (Orange/Gelb) - Für Vorsichts-Aktionen"""
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["medium"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FCD34D, stop:0.5 #FBBF24, stop:1 #F59E0B);
                color: #1F2937;
                border: none;
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 600;
                font-size: {s['font_size']};
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FDE68A, stop:0.5 #FCD34D, stop:1 #FBBF24);
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FBBF24, stop:1 #D97706);
            }}
            QPushButton:disabled {{
                background: #374151;
                color: #6B7280;
            }}
        """
    
    @staticmethod
    def secondary(size: str = "medium") -> str:
        """Sekundärer Button (Grau) - Für weniger wichtige Aktionen"""
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["medium"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS.BG_ELEVATED}, stop:1 {COLORS.BG_CARD});
                color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 500;
                font-size: {s['font_size']};
            }}
            QPushButton:hover {{
                background: {COLORS.BG_ELEVATED};
                border-color: {COLORS.BORDER_HOVER};
            }}
            QPushButton:pressed {{
                background: {COLORS.BG_CARD};
            }}
            QPushButton:disabled {{
                background: {COLORS.BG_CARD};
                color: {COLORS.TEXT_MUTED};
                border-color: {COLORS.BORDER_SUBTLE};
            }}
        """
    
    @staticmethod
    def info(size: str = "medium") -> str:
        """Info-Button (Blau) - Für Informationen und Hilfe"""
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["medium"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #60A5FA, stop:0.5 #3B82F6, stop:1 #2563EB);
                color: white;
                border: none;
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 600;
                font-size: {s['font_size']};
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #93C5FD, stop:0.5 #60A5FA, stop:1 #3B82F6);
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3B82F6, stop:1 #1D4ED8);
            }}
            QPushButton:disabled {{
                background: #374151;
                color: #6B7280;
            }}
        """
    
    @staticmethod
    def ghost(color: str = "primary") -> str:
        """Transparenter Button mit farbigem Rahmen"""
        color_map = {
            "primary": (COLORS.PRIMARY, COLORS.PRIMARY_DARK, COLORS.PRIMARY_LIGHT),
            "blue": ("#3B82F6", "#2563EB", "#60A5FA"),
            "green": (COLORS.SUCCESS, COLORS.SUCCESS_DARK, COLORS.SUCCESS_BRIGHT),
            "red": (COLORS.ERROR, COLORS.ERROR_DARK, COLORS.ERROR_BRIGHT),
            "gray": (COLORS.TEXT_SECONDARY, COLORS.TEXT_MUTED, COLORS.TEXT_PRIMARY),
        }
        border, hover_border, text_color = color_map.get(color, color_map["primary"])
        
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {text_color};
                border: 2px solid {border};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: rgba(108, 92, 231, 0.1);
                border-color: {hover_border};
                color: white;
            }}
            QPushButton:pressed {{
                background-color: rgba(108, 92, 231, 0.2);
            }}
            QPushButton:disabled {{
                border-color: {COLORS.TEXT_MUTED};
                color: {COLORS.TEXT_MUTED};
            }}
        """
    
    @staticmethod
    def icon_button() -> str:
        """Button für Icons in der Statusleiste"""
        return f"""
            QPushButton {{
                background-color: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_SECONDARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: {COLORS.PRIMARY_SUBTLE};
            }}
        """
    
    @staticmethod
    def flat(color: str = "primary") -> str:
        """Flacher Button ohne Hintergrund - nur Text mit Hover-Effekt"""
        color_map = {
            "primary": COLORS.PRIMARY,
            "success": COLORS.SUCCESS,
            "danger": COLORS.ERROR,
            "warning": COLORS.WARNING,
            "muted": COLORS.TEXT_SECONDARY,
        }
        text_color = color_map.get(color, COLORS.PRIMARY)
        
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {text_color};
                border: none;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: rgba(108, 92, 231, 0.1);
            }}
            QPushButton:pressed {{
                background-color: rgba(108, 92, 231, 0.2);
            }}
            QPushButton:disabled {{
                color: {COLORS.TEXT_MUTED};
            }}
        """
    
    @staticmethod
    def toggle(size: str = "medium") -> str:
        """
        Toggle-Button für Start/Stop Aktionen (checkable).
        Grün wenn unchecked (Start), Rot wenn checked (Stop).
        
        Verwendung:
            btn.setCheckable(True)
            btn.setStyleSheet(ButtonStyles.toggle())
        """
        s = ButtonStyles._SIZES.get(size, ButtonStyles._SIZES["medium"])
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34D399, stop:0.5 #10B981, stop:1 #059669);
                color: white;
                border: none;
                border-radius: {s['border_radius']};
                padding: {s['padding']};
                font-weight: 700;
                font-size: {s['font_size']};
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4ADE80, stop:0.5 #22C55E, stop:1 #16A34A);
            }}
            QPushButton:checked {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FB7185, stop:0.5 #F43F5E, stop:1 #E11D48);
            }}
            QPushButton:checked:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FDA4AF, stop:0.5 #FB7185, stop:1 #F43F5E);
            }}
            QPushButton:disabled {{
                background: #374151;
                color: #6B7280;
            }}
        """


# =============================================================================
# CARD STYLES (Dashboard-Karten, Stat-Cards, Info-Cards)
# =============================================================================

class CardStyles:
    """
    Moderne Card-Styles für Dashboard-Elemente und Info-Panels.
    
    Verwendung:
        card.setStyleSheet(CardStyles.default())
        card.setStyleSheet(CardStyles.elevated())
        card.setStyleSheet(CardStyles.status("connected"))
    """
    
    @staticmethod
    def default() -> str:
        """Standard Dashboard-Card mit Gradient und Hover-Effekt"""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS.BG_ELEVATED}, stop:1 {COLORS.BG_CARD});
                border-radius: 8px;
                border: 1px solid {COLORS.BORDER_DEFAULT};
            }}
            QFrame:hover {{
                border: 1px solid rgba(168, 85, 247, 0.3);
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """
    
    @staticmethod
    def elevated() -> str:
        """Erhöhte Card mit stärkerem Gradient und Glow"""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(50, 50, 80, 0.95),
                    stop:0.5 rgba(40, 40, 65, 0.95),
                    stop:1 rgba(30, 30, 50, 0.95));
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }}
            QFrame:hover {{
                border: 1px solid rgba(168, 85, 247, 0.4);
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(55, 55, 90, 0.95),
                    stop:0.5 rgba(45, 45, 70, 0.95),
                    stop:1 rgba(35, 35, 55, 0.95));
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """
    
    @staticmethod
    def glass() -> str:
        """Glasmorphism-Style Card"""
        return f"""
            QFrame {{
                background: rgba(30, 30, 50, 0.7);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }}
            QFrame:hover {{
                background: rgba(35, 35, 55, 0.75);
                border: 1px solid rgba(168, 85, 247, 0.25);
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """
    
    @staticmethod
    def status(state: str = "default") -> str:
        """
        Card mit farbiger Status-Anzeige.
        
        Args:
            state: "default", "connected", "disconnected", "warning", "info"
        """
        status_colors = {
            "default": (COLORS.BORDER_DEFAULT, "rgba(168, 85, 247, 0.15)"),
            "connected": (COLORS.SUCCESS, "rgba(76, 175, 80, 0.15)"),
            "disconnected": (COLORS.ERROR, "rgba(244, 67, 54, 0.15)"),
            "warning": (COLORS.WARNING, "rgba(255, 165, 0, 0.15)"),
            "info": (COLORS.INFO, "rgba(33, 150, 243, 0.15)"),
        }
        border_color, bg_tint = status_colors.get(state, status_colors["default"])
        
        # Base colors from stat_card to match requested gradient
        base_top = "rgba(50, 45, 75, 0.9)"
        base_bottom = "rgba(35, 35, 55, 0.85)"
        
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                    stop:0 {base_top},
                    stop:1 {base_bottom});
                border-radius: 8px;
                border: 2px solid {border_color};
            }}
            QFrame:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                    stop:0 {bg_tint},
                    stop:1 {base_bottom});
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """
    
    @staticmethod
    def stat_card() -> str:
        """Kompakte Statistik-Card für Dashboards"""
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                    stop:0 rgba(50, 45, 75, 0.9),
                    stop:1 rgba(35, 35, 55, 0.85));
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.06);
            }}
            QFrame:hover {{
                border: 1px solid rgba(168, 85, 247, 0.35);
                background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                    stop:0 rgba(55, 50, 85, 0.92),
                    stop:1 rgba(40, 40, 60, 0.88));
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """
    
    @staticmethod
    def device_card(connected: bool = False) -> str:
        """
        Geräte-Status-Card mit Verbindungsanzeige.
        
        Args:
            connected: True wenn Gerät verbunden ist
        """
        # Base colors from stat_card to match requested gradient
        base_top = "rgba(50, 45, 75, 0.9)"
        base_bottom = "rgba(35, 35, 55, 0.85)"
        
        if connected:
            return f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(76, 175, 80, 0.2),
                        stop:1 {base_bottom});
                    border-radius: 8px;
                    border: 2px solid {COLORS.SUCCESS};
                }}
                QFrame:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(76, 175, 80, 0.3),
                        stop:1 rgba(45, 45, 75, 0.95));
                    border: 2px solid {COLORS.SUCCESS_BRIGHT};
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """
        else:
            return f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 {base_top},
                        stop:1 {base_bottom});
                    border-radius: 8px;
                    border: 2px solid {COLORS.TEXT_MUTED};
                }}
                QFrame:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(65, 60, 95, 0.95),
                        stop:1 rgba(45, 45, 75, 0.9));
                    border: 2px solid {COLORS.TEXT_SECONDARY};
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """
    
    @staticmethod
    def plugin_card(connected: bool = False) -> str:
        """
        Custom card style for plugin-based interfaces.
        Uses a light blue border when not connected.
        """
        base_top = "rgba(50, 45, 75, 0.9)"
        base_bottom = "rgba(35, 35, 55, 0.85)"
        
        if connected:
            return CardStyles.device_card(connected=True)
        else:
            return f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 {base_top},
                        stop:1 {base_bottom});
                    border-radius: 8px;
                    border: 2px solid {COLORS.INFO};
                }}
                QFrame:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(65, 60, 95, 0.95),
                        stop:1 rgba(45, 45, 75, 0.9));
                    border: 2px solid {COLORS.INFO_BRIGHT};
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """

    @staticmethod
    def outbound_plugin_card(connected: bool = False) -> str:
        """
        Custom card style for outbound plugins.
        Uses a purple/violet theme to distinguish from hardware.
        """
        base_top = "rgba(60, 50, 90, 0.9)"
        base_bottom = "rgba(35, 35, 55, 0.85)"
        border_color = "#A855F7" # Purple
        hover_color = "#C084FC"
        
        if connected:
            return f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(168, 85, 247, 0.2),
                        stop:1 {base_bottom});
                    border-radius: 8px;
                    border: 2px solid {border_color};
                }}
                QFrame:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(168, 85, 247, 0.3),
                        stop:1 rgba(45, 45, 75, 0.95));
                    border: 2px solid {hover_color};
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """
        else:
            return f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 {base_top},
                        stop:1 {base_bottom});
                    border-radius: 8px;
                    border: 1px solid {border_color};
                    border-style: dashed;
                }}
                QFrame:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0.5, y2:1,
                        stop:0 rgba(70, 60, 100, 0.95),
                        stop:1 rgba(45, 45, 75, 0.9));
                    border: 1px solid {hover_color};
                    border-style: solid;
                }}
                QLabel {{
                    background: transparent;
                    border: none;
                }}
            """

    @staticmethod
    def info_panel() -> str:
        """Großes Info-Panel für Details"""
        return f"""
            QFrame {{
                background: {COLORS.BG_CARD};
                border-radius: 8px;
                border: 1px solid {COLORS.BORDER_DEFAULT};
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """
    
    @staticmethod
    def metric_card(accent_color: str = None) -> str:
        """
        Metriken-Card mit optionalem Farbakzent.
        
        Args:
            accent_color: Hex-Farbe für den oberen Akzent-Streifen
        """
        accent = accent_color or COLORS.PRIMARY
        return f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS.BG_ELEVATED},
                    stop:0.02 {COLORS.BG_ELEVATED},
                    stop:1 {COLORS.BG_CARD});
                border-radius: 8px;
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-top: 3px solid {accent};
            }}
            QFrame:hover {{
                border: 1px solid rgba(168, 85, 247, 0.3);
                border-top: 3px solid {accent};
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """


# =============================================================================
# VERBINDUNGS-STATUS STYLES (Dynamische Border-Signalisierung)
# =============================================================================

class ConnectionStyles:
    """
    Styles für Verbindungsstatus-Anzeige via Border-Farben.
    Diese werden dynamisch angewendet basierend auf dem Verbindungsstatus.
    """
    
    @staticmethod
    def connected() -> str:
        """Grüner Rahmen - Gerät verbunden"""
        return f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {COLORS.SUCCESS};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 12px;
                min-height: 22px;
                max-height: 22px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QPushButton:hover {{
                background-color: rgba(76, 175, 80, 0.15);
                border-color: {COLORS.SUCCESS_DARK};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: rgba(76, 175, 80, 0.3);
                border-color: #2e6830;
                color: {COLORS.TEXT_PRIMARY};
            }}
        """
    
    @staticmethod
    def disconnected() -> str:
        """Roter Rahmen - Gerät nicht verbunden"""
        return f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {COLORS.ERROR};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 12px;
                min-height: 22px;
                max-height: 22px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QPushButton:hover {{
                background-color: rgba(244, 67, 54, 0.15);
                border-color: {COLORS.ERROR_DARK};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QPushButton:pressed {{
                background-color: rgba(244, 67, 54, 0.3);
                border-color: #b71c1c;
                color: {COLORS.TEXT_PRIMARY};
            }}
        """
    
    @staticmethod
    def warning() -> str:
        """Oranger Rahmen - Warnung/Teilweise verbunden"""
        return f"""
            QPushButton {{
                background-color: transparent;
                border: 2px solid {COLORS.WARNING};
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 12px;
                min-height: 22px;
                max-height: 22px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 165, 0, 0.15);
                border-color: {COLORS.WARNING_DARK};
            }}
            QPushButton:pressed {{
                background-color: rgba(255, 165, 0, 0.3);
            }}
        """


# =============================================================================
# STATUS INDICATOR STYLES (LED-artige Anzeigen mit Glow)
# =============================================================================

class StatusIndicator:
    """
    Styles für LED-artige Status-Indikatoren mit optionalem Glow-Effekt.
    
    Verwendung:
        # Einfacher Style
        indicator.setStyleSheet(StatusIndicator.online())
        
        # Mit Glow-Effekt
        indicator.setStyleSheet(StatusIndicator.online(glow=True))
        indicator.setGraphicsEffect(StatusIndicator.create_glow("online"))
    """
    
    SIZE = 16  # Standard-Größe in Pixel
    SIZE_SMALL = 12
    SIZE_LARGE = 20
    
    # Status-Farben Mapping
    _COLORS = {
        "online": COLORS.SUCCESS,
        "success": COLORS.SUCCESS,
        "connected": COLORS.SUCCESS,
        "offline": COLORS.ERROR,
        "error": COLORS.ERROR,
        "disconnected": COLORS.ERROR,
        "warning": COLORS.WARNING,
        "pending": COLORS.WARNING,
        "inactive": COLORS.TEXT_MUTED,
        "neutral": COLORS.TEXT_MUTED,
        "info": COLORS.INFO,
        "loading": COLORS.INFO,
    }
    
    @staticmethod
    def _get_style(color: str, size: int = 16, glow: bool = False) -> str:
        """Generiert den CSS-Style für einen Indikator"""
        radius = size // 2
        base_style = f"""
            background-color: {color};
            border-radius: {radius}px;
            min-width: {size}px;
            min-height: {size}px;
            max-width: {size}px;
            max-height: {size}px;
        """
        
        if glow:
            # Hellere Border für subtilen Glow-Effekt im CSS
            base_style += f"""
            border: 2px solid rgba(255, 255, 255, 0.25);
            """
        
        return base_style
    
    @staticmethod
    def online(size: int = 16, glow: bool = False) -> str:
        """Grüner Indikator - Online/Aktiv"""
        return StatusIndicator._get_style(COLORS.SUCCESS, size, glow)
    
    @staticmethod
    def offline(size: int = 16, glow: bool = False) -> str:
        """Roter Indikator - Offline/Fehler"""
        return StatusIndicator._get_style(COLORS.ERROR, size, glow)
    
    @staticmethod
    def warning(size: int = 16, glow: bool = False) -> str:
        """Oranger Indikator - Warnung"""
        return StatusIndicator._get_style(COLORS.WARNING, size, glow)
    
    @staticmethod
    def inactive(size: int = 16, glow: bool = False) -> str:
        """Grauer Indikator - Inaktiv/Neutral"""
        return StatusIndicator._get_style(COLORS.TEXT_MUTED, size, glow)
    
    @staticmethod
    def info(size: int = 16, glow: bool = False) -> str:
        """Blauer Indikator - Information/Laden"""
        return StatusIndicator._get_style(COLORS.INFO, size, glow)
    
    @staticmethod
    def get(status: str, size: int = 16, glow: bool = False) -> str:
        """
        Universelle Methode für Status-Indikatoren.
        
        Args:
            status: "online", "offline", "warning", "inactive", "info", etc.
            size: Größe in Pixel
            glow: Ob Glow-Effekt angewendet werden soll
        """
        color = StatusIndicator._COLORS.get(status.lower(), COLORS.TEXT_MUTED)
        return StatusIndicator._get_style(color, size, glow)
    
    @staticmethod
    def create_glow(status: str, blur_radius: int = 15, intensity: int = 180) -> QGraphicsDropShadowEffect:
        """
        Erstellt einen Glow-Effekt für einen Status-Indikator.
        
        Args:
            status: "online", "offline", "warning", "info", etc.
            blur_radius: Unschärfe-Radius des Glows
            intensity: Farbintensität (0-255)
        
        Returns:
            QGraphicsDropShadowEffect zum Anwenden auf Widget
        
        Verwendung:
            indicator.setGraphicsEffect(StatusIndicator.create_glow("online"))
        """
        color_hex = StatusIndicator._COLORS.get(status.lower(), COLORS.TEXT_MUTED)
        
        # Hex zu RGB konvertieren
        color = QColor(color_hex)
        glow_color = QColor(color.red(), color.green(), color.blue(), intensity)
        
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(blur_radius)
        effect.setColor(glow_color)
        effect.setOffset(0, 0)
        
        return effect
    
    @staticmethod
    def pulsing_style(status: str, size: int = 16) -> str:
        """
        Style für pulsierende Indikatoren (CSS-Animation).
        Hinweis: Funktioniert nur mit QSS-Animation-Support.
        
        Args:
            status: Status-Name
            size: Größe in Pixel
        """
        color = StatusIndicator._COLORS.get(status.lower(), COLORS.TEXT_MUTED)
        radius = size // 2
        
        return f"""
            background-color: {color};
            border-radius: {radius}px;
            min-width: {size}px;
            min-height: {size}px;
            max-width: {size}px;
            max-height: {size}px;
            border: 2px solid rgba(255, 255, 255, 0.3);
        """


# =============================================================================
# STATUS TEXT STYLES
# =============================================================================

class StatusText:
    """Styles für Status-Texte (verbunden, nicht verbunden, etc.)"""
    
    @staticmethod
    def success() -> str:
        return f"color: {COLORS.SUCCESS}; font-weight: bold;"
    
    @staticmethod
    def error() -> str:
        return f"color: {COLORS.ERROR}; font-weight: bold;"
    
    @staticmethod
    def warning() -> str:
        return f"color: {COLORS.WARNING}; font-weight: bold;"
    
    @staticmethod
    def info() -> str:
        return f"color: {COLORS.INFO}; font-weight: bold;"
    
    @staticmethod
    def muted() -> str:
        return f"color: {COLORS.TEXT_MUTED}; font-weight: bold;"
    
    @staticmethod
    def with_size(color: str, size: int = 13) -> str:
        """Status-Text mit anpassbarer Größe"""
        return f"color: {color}; font-weight: bold; font-size: {size}px; background-color: transparent; border: none; margin: 0; padding: 0;"


# =============================================================================
# GROUPBOX STYLES (mit Status-Rahmen-Unterstützung)
# =============================================================================

class GroupBoxStyles:
    """
    Moderne Styles für GroupBoxes mit verschiedenen Varianten.
    
    Verwendung:
        group_box.setStyleSheet(GroupBoxStyles.modern())
        group_box.setStyleSheet(GroupBoxStyles.with_status("success"))
    """
    
    @staticmethod
    def default() -> str:
        """Standard GroupBox - Clean und subtil"""
        return f"""
            QGroupBox {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px 10px 10px 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 4px 12px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.PRIMARY}, stop:1 {COLORS.PRIMARY_LIGHT});
                border-radius: 6px;
                color: white;
                font-size: 12px;
            }}
        """
    
    @staticmethod
    def tight() -> str:
        """Extra kompakte Variante für Platz-kritische Bereiche"""
        return GroupBoxStyles.default()
    
    @staticmethod
    def modern() -> str:
        """Moderne GroupBox mit Gradient-Titel - Alias für default()"""
        return GroupBoxStyles.default()
    
    @staticmethod
    def subtle() -> str:
        """Dezente GroupBox ohne Hintergrund-Hervorhebung"""
        return f"""
            QGroupBox {{
                background-color: transparent;
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px 10px 10px 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 4px 12px;
                background: {COLORS.BG_ELEVATED};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 6px;
                color: {COLORS.TEXT_SECONDARY};
                font-size: 12px;
            }}
        """
    
    @staticmethod
    def with_status(status: Literal["default", "success", "error", "warning", "info"] = "default") -> str:
        """
        GroupBox mit Status-Rahmenfarbe für dynamische Signalisierung.
        Verwendet die moderne Basis-Style mit farbigem Rahmen.
        
        Args:
            status: "default" (lila), "success" (grün), "error" (rot), 
                   "warning" (orange), "info" (blau)
        
        Beispiel:
            # Dynamisch basierend auf Verbindungsstatus
            if is_connected:
                group.setStyleSheet(GroupBoxStyles.with_status("success"))
            else:
                group.setStyleSheet(GroupBoxStyles.with_status("error"))
        """
        status_config = {
            "default": (COLORS.PRIMARY, COLORS.PRIMARY_LIGHT),
            "success": (COLORS.SUCCESS, COLORS.SUCCESS_BRIGHT),
            "error": (COLORS.ERROR, COLORS.ERROR_BRIGHT),
            "warning": (COLORS.WARNING, COLORS.WARNING_BRIGHT),
            "info": (COLORS.INFO, COLORS.INFO_BRIGHT),
        }
        border_color, title_accent = status_config.get(status, status_config["default"])
        
        return f"""
            QGroupBox {{
                background-color: {COLORS.BG_CARD};
                border: 2px solid {border_color};
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px 10px 10px 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 4px 12px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {border_color}, stop:1 {title_accent});
                border-radius: 6px;
                color: white;
                font-size: 12px;
            }}
        """
    
    @staticmethod
    def elevated() -> str:
        """Erhöhte GroupBox mit leichtem Glow-Effekt für wichtige Bereiche"""
        return f"""
            QGroupBox {{
                background-color: {COLORS.BG_ELEVATED};
                border: 1px solid {COLORS.BORDER_HOVER};
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px 10px 10px 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 16px;
                padding: 5px 14px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.PRIMARY}, stop:1 {COLORS.PRIMARY_LIGHT});
                border-radius: 7px;
                color: white;
                font-size: 13px;
                font-weight: 600;
            }}
            QGroupBox:hover {{
                border: 1px solid rgba(108, 92, 231, 0.4);
            }}
        """
    
    @staticmethod
    def compact() -> str:
        """Kompakte GroupBox für platzsparende Bereiche"""
        return f"""
            QGroupBox {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px 10px 10px 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 3px 10px;
                background: {COLORS.BG_ELEVATED};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 5px;
                color: {COLORS.TEXT_PRIMARY};
                font-size: 11px;
            }}
        """
    
    @staticmethod
    def section() -> str:
        """Große Sektion-GroupBox für Hauptbereiche"""
        return f"""
            QGroupBox {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px 10px 10px 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 18px;
                padding: 6px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(108, 92, 231, 0.9), stop:1 rgba(162, 155, 254, 0.9));
                border-radius: 8px;
                color: white;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: 0.3px;
            }}
        """


# =============================================================================
# INPUT FIELD STYLES
# =============================================================================

class InputStyles:
    """Styles für Eingabefelder"""
    
    @staticmethod
    def default() -> str:
        """Standard Input-Feld"""
        return f"""
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
                background-color: {COLORS.BG_INPUT};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 6px 8px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
                border-color: {COLORS.PRIMARY};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 8px;
            }}
        """
    
    @staticmethod
    def readonly() -> str:
        """Nur-Lese Input-Feld"""
        return f"""
            QLineEdit {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_SUBTLE};
                border-radius: 4px;
                padding: 6px 8px;
                color: {COLORS.TEXT_SECONDARY};
            }}
        """


# =============================================================================
# TABLE STYLES
# =============================================================================

class TableStyles:
    """Styles für Tabellen"""
    
    @staticmethod
    def default() -> str:
        return f"""
            QTableWidget {{
                background-color: {COLORS.BG_DARK};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 4px;
                gridline-color: {COLORS.BORDER_SUBTLE};
            }}
            QTableWidget::item {{
                padding: 5px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QTableWidget::item:selected {{
                background-color: rgba(108, 92, 231, 0.45);
            }}
            QHeaderView::section {{
                background-color: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_SECONDARY};
                padding: 8px;
                border: none;
                border-bottom: 1px solid {COLORS.BORDER_DEFAULT};
                font-weight: bold;
            }}
            /* Improvement for checkbox visibility in tables */
            QTableWidget::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid rgba(255, 255, 255, 0.3);
                background-color: {COLORS.BG_INPUT};
            }}
            QTableWidget::indicator:checked {{
                background-color: {COLORS.PRIMARY};
                border-color: {COLORS.PRIMARY};
            }}
            /* Also style QCheckBoxes inside the table */
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid rgba(255, 255, 255, 0.3);
                background-color: {COLORS.BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.PRIMARY};
                border-color: {COLORS.PRIMARY};
            }}
        """


# =============================================================================
# TAB WIDGET STYLES
# =============================================================================

class TabStyles:
    """Styles für Tab-Widgets"""
    
    @staticmethod
    def default() -> str:
        return f"""
            QTabWidget::pane {{
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                background-color: {COLORS.BG_CARD};
            }}
            QTabBar::tab {{
                background-color: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_SECONDARY};
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QTabBar::tab:hover {{
                background-color: {COLORS.BG_ELEVATED};
            }}
        """


# =============================================================================
# GRAPH STYLES
# =============================================================================

class GraphStyles:
    """
    Styles für PyQtGraph Widgets.
    
    Verwendung:
        GraphStyles.apply_dark_theme(plot_widget)
        GraphStyles.apply_spectrum_theme(fft_plot)
        GraphStyles.configure_axis(plot_widget, 'bottom', 'Zeit', 's')
    """
    
    # Basis-Farben für Graphen (können überschrieben werden)
    GRAPH_BACKGROUND = "#0F0F1A"        # Dunkler Hintergrund
    GRAPH_BACKGROUND_ALT = "#1a1a2e"    # Alternativer Hintergrund
    GRID_COLOR = "#404050"              # Grid-Linien
    AXIS_COLOR = "#606070"              # Achsen
    TEXT_COLOR = "#A0A0B0"              # Achsen-Text
    TITLE_COLOR = "#FFFFFF"             # Titel
    
    @staticmethod
    def apply_dark_theme(widget, show_grid: bool = True, grid_alpha: float = 0.2) -> None:
        """
        Wendet das dunkle Theme auf ein PyQtGraph PlotWidget an.
        
        Args:
            widget: PyQtGraph PlotWidget
            show_grid: Grid anzeigen
            grid_alpha: Transparenz des Grids (0.0-1.0)
        """
        widget.setBackground(COLORS.GRAPH_BG)
        widget.getAxis('bottom').setPen(COLORS.GRAPH_AXIS)
        widget.getAxis('left').setPen(COLORS.GRAPH_AXIS)
        widget.getAxis('bottom').setTextPen(COLORS.GRAPH_TEXT)
        widget.getAxis('left').setTextPen(COLORS.GRAPH_TEXT)
        if show_grid:
            widget.showGrid(x=True, y=True, alpha=grid_alpha)
    
    @staticmethod
    def apply_modern_theme(widget, accent_color: str = None) -> None:
        """
        Wendet ein modernes, dunkleres Theme an.
        
        Args:
            widget: PyQtGraph PlotWidget
            accent_color: Optionale Akzentfarbe für Highlights
        """
        widget.setBackground(GraphStyles.GRAPH_BACKGROUND)
        
        # Moderne Achsen-Styles
        for axis_name in ['bottom', 'left']:
            axis = widget.getAxis(axis_name)
            axis.setPen(GraphStyles.GRID_COLOR)
            axis.setTextPen(GraphStyles.TEXT_COLOR)
        
        # Subtiles Grid
        widget.showGrid(x=True, y=True, alpha=0.15)
        
        # ViewBox Hintergrund
        try:
            widget.getPlotItem().getViewBox().setBackgroundColor(GraphStyles.GRAPH_BACKGROUND)
        except:
            pass
    
    @staticmethod
    def apply_spectrum_theme(widget) -> None:
        """
        Spezielle Styles für FFT/Spektrum-Plots.
        Optimiert für Frequenzanalyse mit Log-Skala Support.
        """
        widget.setBackground(GraphStyles.GRAPH_BACKGROUND)
        
        # Achsen für Frequenzdarstellung
        widget.getAxis('bottom').setPen("#505060")
        widget.getAxis('left').setPen("#505060")
        widget.getAxis('bottom').setTextPen("#B0B0C0")
        widget.getAxis('left').setTextPen("#B0B0C0")
        
        # Feineres Grid für Präzision
        widget.showGrid(x=True, y=True, alpha=0.25)
        
        # Enable mouse interaction
        widget.setMouseEnabled(x=True, y=True)
    
    @staticmethod
    def apply_histogram_theme(widget) -> None:
        """
        Styles für Histogramm-Plots.
        """
        widget.setBackground(GraphStyles.GRAPH_BACKGROUND_ALT)
        
        widget.getAxis('bottom').setPen("#404050")
        widget.getAxis('left').setPen("#404050")
        widget.getAxis('bottom').setTextPen(GraphStyles.TEXT_COLOR)
        widget.getAxis('left').setTextPen(GraphStyles.TEXT_COLOR)
        
        widget.showGrid(x=True, y=True, alpha=0.2)
    
    @staticmethod
    def apply_realtime_theme(widget) -> None:
        """
        Styles für Echtzeit-Daten-Plots (Datenrate, Live-Monitoring).
        Optimiert für kontinuierliche Updates.
        """
        widget.setBackground(GraphStyles.GRAPH_BACKGROUND_ALT)
        
        widget.getAxis('bottom').setPen("#404050")
        widget.getAxis('left').setPen("#404050")
        widget.getAxis('bottom').setTextPen(GraphStyles.TEXT_COLOR)
        widget.getAxis('left').setTextPen(GraphStyles.TEXT_COLOR)
        
        # Stärkeres Grid für bessere Ablesbarkeit
        widget.showGrid(x=True, y=True, alpha=0.3)
    
    @staticmethod
    def apply_calibration_theme(widget) -> None:
        """
        Styles für Kalibrierungs-Plots.
        Optimiert für Vergleich von Messwerten.
        """
        widget.setBackground(GraphStyles.GRAPH_BACKGROUND_ALT)
        
        widget.getAxis('bottom').setPen("#404050")
        widget.getAxis('left').setPen("#404050")
        widget.getAxis('bottom').setTextPen(GraphStyles.TEXT_COLOR)
        widget.getAxis('left').setTextPen(GraphStyles.TEXT_COLOR)
        
        widget.showGrid(x=True, y=True, alpha=0.3)
    
    @staticmethod
    def configure_axis(widget, axis: str, label: str, units: str = None, 
                       pen_color: str = None, text_color: str = None) -> None:
        """
        Konfiguriert eine einzelne Achse.
        
        Args:
            widget: PyQtGraph PlotWidget
            axis: 'bottom', 'left', 'top', 'right'
            label: Achsen-Beschriftung
            units: Einheit (optional)
            pen_color: Farbe der Achse
            text_color: Farbe des Texts
        """
        ax = widget.getAxis(axis)
        
        if pen_color:
            ax.setPen(pen_color)
        if text_color:
            ax.setTextPen(text_color)
        
        if units:
            widget.setLabel(axis, label, units)
        else:
            widget.setLabel(axis, label)
    
    @staticmethod
    def get_line_colors(count: int = 10) -> list:
        """
        Gibt eine Liste von Farben für mehrere Linien zurück.
        
        Args:
            count: Anzahl der benötigten Farben
        
        Returns:
            Liste von Hex-Farbcodes
        """
        from app.ui.theme import SENSOR_COLORS
        colors = []
        for i in range(count):
            colors.append(SENSOR_COLORS[i % len(SENSOR_COLORS)])
        return colors
    
    @staticmethod
    def create_pen(color: str, width: int = 2, style: str = "solid"):
        """
        Erstellt einen PyQtGraph-kompatiblen Pen.
        
        Args:
            color: Hex-Farbcode
            width: Linienbreite
            style: "solid", "dash", "dot", "dashdot"
        
        Returns:
            dict für pg.mkPen()
        """
        import pyqtgraph as pg
        from PyQt6.QtCore import Qt
        
        style_map = {
            "solid": Qt.PenStyle.SolidLine,
            "dash": Qt.PenStyle.DashLine,
            "dot": Qt.PenStyle.DotLine,
            "dashdot": Qt.PenStyle.DashDotLine,
        }
        
        return pg.mkPen(color=color, width=width, style=style_map.get(style, Qt.PenStyle.SolidLine))


# =============================================================================
# STATUSBAR STYLES
# =============================================================================

class StatusBarStyles:
    """Styles für die Statusleiste"""
    
    @staticmethod
    def default() -> str:
        return f"""
            QStatusBar {{
                background-color: {COLORS.BG_CARD};
                color: {COLORS.TEXT_SECONDARY};
                border-top: 1px solid {COLORS.BORDER_DEFAULT};
            }}
            QStatusBar::item {{
                border: none;
            }}
        """


# =============================================================================
# SCROLL AREA STYLES
# =============================================================================

class ScrollStyles:
    """Styles für Scrollbereiche"""
    
    @staticmethod
    def default() -> str:
        return f"""
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background-color: {COLORS.BG_CARD};
                width: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {COLORS.TEXT_MUTED};
                border-radius: 5px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {COLORS.TEXT_SECONDARY};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """


# =============================================================================
# HELPER FUNKTIONEN
# =============================================================================

def create_shadow_effect(
    blur_radius: int = 25,
    color: QColor = None,
    offset_x: int = 4,
    offset_y: int = 4
) -> QGraphicsDropShadowEffect:
    """
    Erstellt einen Schatten-Effekt für Widgets.
    
    Args:
        blur_radius: Unschärfe-Radius
        color: Schattenfarbe (QColor)
        offset_x: Horizontaler Versatz
        offset_y: Vertikaler Versatz
    
    Returns:
        QGraphicsDropShadowEffect
    """
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur_radius)
    shadow.setColor(color if color else QColor(0, 0, 0, 100))
    shadow.setOffset(offset_x, offset_y)
    return shadow


def create_glow_effect(
    blur_radius: int = 20,
    color: QColor = None
) -> QGraphicsDropShadowEffect:
    """
    Erstellt einen Glow-Effekt für Widgets (Schatten ohne Offset).
    
    Args:
        blur_radius: Unschärfe-Radius
        color: Glow-Farbe (QColor)
    
    Returns:
        QGraphicsDropShadowEffect
    """
    glow = QGraphicsDropShadowEffect()
    glow.setBlurRadius(blur_radius)
    glow.setColor(color if color else QColor(168, 85, 247, 60))  # Purple glow
    glow.setOffset(0, 0)
    return glow


def create_status_glow(
    status: str,
    blur_radius: int = 15,
    intensity: int = 150
) -> QGraphicsDropShadowEffect:
    """
    Erstellt einen farbigen Glow-Effekt basierend auf Status.
    
    Args:
        status: "online", "offline", "warning", "info", "success", "error"
        blur_radius: Unschärfe-Radius
        intensity: Farbintensität/Alpha (0-255)
    
    Returns:
        QGraphicsDropShadowEffect
    
    Verwendung:
        indicator.setGraphicsEffect(create_status_glow("online"))
    """
    # Status-Farben Mapping
    status_colors = {
        "online": COLORS.SUCCESS,
        "success": COLORS.SUCCESS,
        "connected": COLORS.SUCCESS,
        "offline": COLORS.ERROR,
        "error": COLORS.ERROR,
        "disconnected": COLORS.ERROR,
        "warning": COLORS.WARNING,
        "pending": COLORS.WARNING,
        "info": COLORS.INFO,
        "loading": COLORS.INFO,
    }
    
    color_hex = status_colors.get(status.lower(), COLORS.TEXT_MUTED)
    color = QColor(color_hex)
    glow_color = QColor(color.red(), color.green(), color.blue(), intensity)
    
    glow = QGraphicsDropShadowEffect()
    glow.setBlurRadius(blur_radius)
    glow.setColor(glow_color)
    glow.setOffset(0, 0)
    return glow


def get_status_color(status: str) -> str:
    """
    Gibt die passende Farbe für einen Status zurück.
    
    Args:
        status: "success", "error", "warning", "info", "muted"
    
    Returns:
        Hex-Farbcode
    """
    status_colors = {
        "success": COLORS.SUCCESS,
        "connected": COLORS.SUCCESS,
        "online": COLORS.SUCCESS,
        "error": COLORS.ERROR,
        "disconnected": COLORS.ERROR,
        "offline": COLORS.ERROR,
        "warning": COLORS.WARNING,
        "pending": COLORS.WARNING,
        "info": COLORS.INFO,
        "muted": COLORS.TEXT_MUTED,
        "inactive": COLORS.TEXT_MUTED,
    }
    return status_colors.get(status.lower(), COLORS.TEXT_MUTED)


# =============================================================================
# DIALOG STYLES
# =============================================================================

class DialogStyles:
    """
    Styles für Popup-Dialoge, um konsistentes dunkles Theme zu gewährleisten.
    
    Verwendung:
        dialog = QDialog(self)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
    """
    
    @staticmethod
    def dark_dialog():
        """Dunkles Theme für Dialoge - passend zum Hauptfenster"""
        return f"""
            QDialog {{
                background-color: {COLORS.BG_DARK};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QLabel {{
                color: {COLORS.TEXT_PRIMARY};
                background: transparent;
            }}
            QGroupBox {{
                color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: bold;
                background-color: {COLORS.BG_CARD};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
                background-color: {COLORS.BG_INPUT};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 4px;
                padding: 6px 8px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
                border-color: {COLORS.PRIMARY};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {COLORS.TEXT_SECONDARY};
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                selection-background-color: rgba(108, 92, 231, 0.45);
            }}
            QCheckBox {{
                color: {COLORS.TEXT_PRIMARY};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid rgba(255, 255, 255, 0.3);
                background-color: {COLORS.BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.PRIMARY};
                border-color: {COLORS.PRIMARY};
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {COLORS.BG_INPUT};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS.PRIMARY};
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLORS.PRIMARY};
                border-radius: 3px;
            }}
            QListWidget {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QListWidget::item {{
                padding: 8px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: rgba(108, 92, 231, 0.45);
            }}
            QListWidget::item:hover {{
                background-color: {COLORS.BG_ELEVATED};
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                background: {COLORS.BG_CARD};
            }}
            QTabBar::tab {{
                background: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_SECONDARY};
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QProgressBar {{
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 4px;
                background-color: {COLORS.BG_INPUT};
                text-align: center;
                color: {COLORS.TEXT_PRIMARY};
            }}
            QProgressBar::chunk {{
                background-color: {COLORS.PRIMARY};
                border-radius: 3px;
            }}
        """
    
    @staticmethod
    def apply_to_dialog(dialog):
        """Apply dark dialog style to a QDialog instance"""
        dialog.setStyleSheet(DialogStyles.dark_dialog())


# =============================================================================
# TYPOGRAPHY (Schriftarten und Text-Styles)
# =============================================================================

class Typography:
    """
    Zentrales Schriftarten-System für konsistente Typografie.
    
    Empfohlene Schriftarten:
    - UI-Text: Inter, Segoe UI, SF Pro Display
    - Code/Daten: JetBrains Mono, Fira Code, Consolas
    
    Verwendung:
        label.setFont(Typography.heading())
        code_label.setFont(Typography.code())
        Typography.apply_to_app(app)
    """
    
    # Schriftfamilien
    FONT_FAMILY_UI = '"Inter", "Segoe UI", "SF Pro Display", system-ui, sans-serif'
    FONT_FAMILY_CODE = '"JetBrains Mono", "Fira Code", "Consolas", "Monaco", monospace'
    FONT_FAMILY_DISPLAY = '"Inter", "SF Pro Display", "Segoe UI", sans-serif'
    
    # Standard Font-Größen
    SIZE_XS = 10
    SIZE_SM = 11
    SIZE_BASE = 13
    SIZE_MD = 14
    SIZE_LG = 16
    SIZE_XL = 20
    SIZE_2XL = 24
    SIZE_3XL = 32
    
    @staticmethod
    def heading(size: int = 20, bold: bool = True) -> QFont:
        """Überschriften-Font"""
        font = QFont("Inter", size)
        if bold:
            font.setWeight(QFont.Weight.Bold)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def subheading(size: int = 16, bold: bool = True) -> QFont:
        """Unterüberschriften-Font"""
        font = QFont("Inter", size)
        if bold:
            font.setWeight(QFont.Weight.DemiBold)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def body(size: int = 13) -> QFont:
        """Standard Text-Font"""
        font = QFont("Segoe UI", size)
        font.setWeight(QFont.Weight.Normal)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def body_bold(size: int = 13) -> QFont:
        """Fetter Text-Font"""
        font = QFont("Segoe UI", size)
        font.setWeight(QFont.Weight.Bold)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def caption(size: int = 11) -> QFont:
        """Kleinerer Beschreibungstext"""
        font = QFont("Segoe UI", size)
        font.setWeight(QFont.Weight.Normal)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def code(size: int = 12) -> QFont:
        """Monospace-Font für Code und Daten"""
        font = QFont("JetBrains Mono", size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        # Fallback auf Consolas wenn JetBrains Mono nicht verfügbar
        if font.family() != "JetBrains Mono":
            font = QFont("Consolas", size)
        return font
    
    @staticmethod
    def data(size: int = 13) -> QFont:
        """Font für Datenwerte (Sensoren, Messwerte)"""
        font = QFont("JetBrains Mono", size)
        font.setWeight(QFont.Weight.Medium)
        font.setStyleHint(QFont.StyleHint.Monospace)
        if font.family() != "JetBrains Mono":
            font = QFont("Consolas", size)
            font.setWeight(QFont.Weight.Medium)
        return font
    
    @staticmethod
    def button(size: int = 13, bold: bool = True) -> QFont:
        """Font für Buttons"""
        font = QFont("Segoe UI", size)
        if bold:
            font.setWeight(QFont.Weight.DemiBold)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def label(size: int = 12) -> QFont:
        """Font für Labels"""
        font = QFont("Segoe UI", size)
        font.setWeight(QFont.Weight.Medium)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        return font
    
    @staticmethod
    def get_css_font_family(type: str = "ui") -> str:
        """
        Gibt die CSS font-family Deklaration zurück.
        
        Args:
            type: "ui", "code", "display"
        """
        families = {
            "ui": Typography.FONT_FAMILY_UI,
            "code": Typography.FONT_FAMILY_CODE,
            "display": Typography.FONT_FAMILY_DISPLAY,
        }
        return families.get(type, Typography.FONT_FAMILY_UI)
    
    @staticmethod
    def load_fonts():
        """
        Lädt benutzerdefinierte Schriftarten aus dem fonts-Ordner.
        Sollte beim App-Start aufgerufen werden.
        """
        from PyQt6.QtGui import QFontDatabase
        import os
        
        fonts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "fonts")
        
        if os.path.exists(fonts_dir):
            for font_file in os.listdir(fonts_dir):
                if font_file.endswith(('.ttf', '.otf')):
                    font_path = os.path.join(fonts_dir, font_file)
                    QFontDatabase.addApplicationFont(font_path)


# =============================================================================
# GLOBALES APPLICATION STYLESHEET
# =============================================================================

def get_application_stylesheet() -> str:
    """
    Gibt ein globales Stylesheet für die gesamte Anwendung zurück.
    Kann auf QApplication angewendet werden.
    """
    return f"""
        /* Globale Basis-Styles */
        QWidget {{
            font-family: {Typography.FONT_FAMILY_UI};
        }}
        
        /* Tooltips */
        QToolTip {{
            background-color: {COLORS.BG_ELEVATED};
            color: {COLORS.TEXT_PRIMARY};
            border: 1px solid {COLORS.BORDER_DEFAULT};
            border-radius: 4px;
            padding: 6px 10px;
        }}
        
        /* Scrollbars global */
        QScrollBar:vertical {{
            background-color: {COLORS.BG_CARD};
            width: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {COLORS.TEXT_MUTED};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {COLORS.TEXT_SECONDARY};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        
        QScrollBar:horizontal {{
            background-color: {COLORS.BG_CARD};
            height: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {COLORS.TEXT_MUTED};
            border-radius: 5px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {COLORS.TEXT_SECONDARY};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
    """


# =============================================================================
# SENSOR FARBEN (für Graphen)
# =============================================================================

# Konsistente Farbpalette für Sensor-Linien in Graphen
SENSOR_COLORS = [
    "#FF6B6B",  # Coral Red
    "#4ECDC4",  # Teal
    "#45B7D1",  # Sky Blue
    "#96CEB4",  # Sage Green
    "#FFEAA7",  # Cream Yellow
    "#DDA0DD",  # Plum
    "#98D8C8",  # Mint
    "#F7DC6F",  # Sunflower
    "#BB8FCE",  # Amethyst
    "#85C1E9",  # Light Blue
    "#F8B500",  # Amber
    "#00CED1",  # Dark Turquoise
]


def get_sensor_color(index: int) -> str:
    """
    Gibt eine Farbe für einen Sensor basierend auf seinem Index zurück.
    Farben werden zyklisch wiederholt.
    
    Args:
        index: Sensor-Index
    
    Returns:
        Hex-Farbcode
    """
    return SENSOR_COLORS[index % len(SENSOR_COLORS)]

