import json
import threading
import requests
import time
import os
import uuid
import re
import html
from datetime import datetime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, 
                             QLineEdit, QPushButton, QTabWidget, QWidget, 
                             QLabel, QFormLayout, QScrollArea, QSplitter,
                             QCheckBox, QFrame, QComboBox, QGridLayout, QSpinBox,
                             QGroupBox, QListWidget, QListWidgetItem, QMenu,
                             QInputDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, pyqtSlot, QSize, QThread
from PyQt6.QtGui import QFont, QTextCursor, QColor, QTextDocument, QIcon, QAction
from app.ui.theme import COLORS, DialogStyles, ButtonStyles, InputStyles, GroupBoxStyles
from app.ui.collapsible_box import CollapsibleBox

class LLMWorker(QObject):
    """Worker for LLM communication that runs in a QThread"""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    partial_response = pyqtSignal(str)
    tool_call_started = pyqtSignal(str)
    tool_call_finished = pyqtSignal(str)
    
    def __init__(self, config, messages, tools, mcp_server):
        super().__init__()
        self.config = config
        self.messages = messages
        self.tools = tools
        self.mcp_server = mcp_server
        self.force_tool_use = False
        self.has_image = False
        self._is_cancelled = False
        self.session = None

    @pyqtSlot()
    def cancel(self):
        self._is_cancelled = True
        if self.session:
            try:
                # Closing the session will break a pending requests.post call
                self.session.close()
            except:
                pass

    @pyqtSlot()
    def run(self):
        # Create session inside the thread to avoid cross-thread timer issues
        self.session = requests.Session()
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config['api_key']}"
            }
            timeout = int(self.config.get("timeout", 300))
            payload = {
                "model": self.config["model"],
                "messages": self.messages,
                "tools": self.tools
            }
            if getattr(self, 'force_tool_use', False):
                payload["tool_choice"] = "required"
            elif self.tools:
                payload["tool_choice"] = "auto"
            
            url = self.config["url"]
            if url.endswith(":1234") or url.endswith(":1234/"):
                url = url.rstrip('/') + "/v1/chat/completions"

            max_iterations = int(self.config.get("max_iterations", 25))
            iteration = 0
            
            while iteration < max_iterations:
                if self._is_cancelled:
                    self.finished.emit("[Query Stopped by User]")
                    return
                iteration += 1
                
                # Scrub messages for local/proxied APIs
                clean_messages = []
                # Only keep the last 2-3 images in full to save bandwidth and speed up processing
                images_found = 0
                for m in reversed(self.messages):
                    if not isinstance(m, dict):
                        continue
                        
                    role = m.get("role", "user")
                    content = m.get("content")
                    if content is None: content = ""
                    
                    # Deep copy message to avoid modifying the original history
                    clean_m = {"role": role, "content": content}
                    if "tool_calls" in m and m["tool_calls"]:
                        clean_m["tool_calls"] = m["tool_calls"]
                    if "tool_call_id" in m: clean_m["tool_call_id"] = m["tool_call_id"]
                    if "name" in m: clean_m["name"] = m["name"]

                    # Truncate old images in multimodal content
                    if isinstance(content, list):
                        new_content = []
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "image_url":
                                images_found += 1
                                if images_found > 2: # Only keep the 2 most recent images
                                    new_content.append({"type": "text", "text": "[Old Image Truncated for Speed]"})
                                else:
                                    new_content.append(part)
                            else:
                                new_content.append(part)
                        clean_m["content"] = new_content
                    
                    # Handle empty strings for some APIs
                    if role in ["user", "assistant"]:
                        if not clean_m.get("content") and "tool_calls" not in clean_m:
                            clean_m["content"] = " "
                    
                    clean_messages.insert(0, clean_m)
                
                # Role alternation validation
                validated_messages = []
                last_role = None
                for i, m in enumerate(clean_messages):
                    current_role = m["role"]
                    
                    # Merge consecutive system messages
                    if current_role == "system":
                        if validated_messages and validated_messages[-1]["role"] == "system":
                            last_msg = validated_messages[-1]
                            if isinstance(last_msg.get("content"), str) and isinstance(m.get("content"), str):
                                last_msg["content"] = f"{last_msg['content']}\n\n{m['content']}".strip()
                                continue
                        validated_messages.append(m)
                        continue
                    
                    # Fix for strict templates (Mistral/Llama3): 
                    # If User follows Tool, we MUST inject an Assistant response in between.
                    if current_role == "user" and last_role == "tool":
                        validated_messages.append({"role": "assistant", "content": "I have received the tool results and visual data."})
                        last_role = "assistant"
                    
                    # Ensure no empty content for user/assistant roles (some APIs fail)
                    if current_role in ["user", "assistant"] and not m.get("content") and "tool_calls" not in m:
                        m["content"] = " "
                    
                    # If we have two consecutive user or assistant messages, merge them
                    if current_role == last_role and current_role in ["user", "assistant"]:
                        if validated_messages:
                            last_msg = validated_messages[-1]
                            old_content = last_msg.get("content")
                            new_content = m.get("content")
                            
                            # Both must be strings to merge as string
                            if isinstance(old_content, str) and isinstance(new_content, str):
                                last_msg["content"] = f"{old_content}\n\n{new_content}".strip()
                                continue
                            else:
                                # Multimodal merge (convert both to lists of parts)
                                def to_parts(c):
                                    if isinstance(c, list): return c
                                    if not c or (isinstance(c, str) and not c.strip()): return []
                                    return [{"type": "text", "text": str(c)}]
                                
                                last_msg["content"] = to_parts(old_content) + to_parts(new_content)
                                # If the merged content is empty, restore a placeholder
                                if not last_msg["content"]:
                                    last_msg["content"] = " "
                                continue
                    
                    validated_messages.append(m)
                    last_role = current_role

                payload["messages"] = validated_messages
                
                try:
                    response = self.session.post(url, json=payload, headers=headers, timeout=timeout)
                    if response.status_code == 400:
                        try:
                            res_json = response.json()
                            if isinstance(res_json, dict):
                                error_detail = res_json.get("error", {}).get("message", response.text)
                            else:
                                error_detail = str(res_json)
                        except:
                            error_detail = response.text
                        self.error.emit(f"API Error (400): {error_detail}")
                        return
                    response.raise_for_status()
                    result = response.json()
                except Exception as e:
                    if self._is_cancelled:
                        self.finished.emit("[Query Stopped by User]")
                        return
                    self.error.emit(f"Request Error: {str(e)}")
                    return
                
                if not isinstance(result, dict) or "choices" not in result or not result["choices"]:
                    if isinstance(result, dict):
                        error_msg = result.get("error", {}).get("message", "Unknown API error")
                    else:
                        error_msg = str(result)
                    
                    if "regex" in error_msg.lower():
                        error_msg += "\n\nTip: Local models often fail tool-call parsing if result is too large."
                    self.error.emit(f"API Error: {error_msg}")
                    return

                choice = result["choices"][0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason")
                
                reasoning = choice.get("reasoning_content") or message.get("reasoning")
                if reasoning:
                    clean_reasoning = reasoning.replace("<thought>", "").replace("</thought>", "").strip()
                    self.tool_call_started.emit(f"AI Thought: {clean_reasoning[:120]}...")
                
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    content = message.get("content", "")
                    mistral_matches = re.finditer(r'\[TOOL_CALLS\]([a-z_][a-z0-9_]*)\[ARGS\](\{.*?\})(?=\[TOOL_CALLS\]|$)', content, re.IGNORECASE | re.DOTALL)
                    for match in mistral_matches:
                        name = match.group(1)
                        args_str = match.group(2)
                        try:
                            args = json.loads(args_str)
                            tool_calls.append({
                                "id": f"call_{uuid.uuid4().hex[:8]}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)}
                            })
                        except: continue
                    if not tool_calls:
                        call_match = re.search(r'(?:to=)?functions\.([a-z_][a-z0-9_]*)(?:json)?\s*([({].*?)$', content, re.IGNORECASE | re.DOTALL)
                        if call_match:
                            name = call_match.group(1)
                            rest = call_match.group(2).strip()
                            args = {}
                            if rest.startswith("("):
                                args_str = rest[1:rest.find(")")] if ")" in rest else rest[1:]
                                try:
                                    if ":" in args_str:
                                        args = json.loads(f"{{{args_str}}}" if not args_str.startswith("{") else args_str)
                                except: pass
                            elif rest.startswith("{"):
                                try: args = json.loads(rest)
                                except:
                                    json_match = re.search(r'(\{.*\})', rest, re.DOTALL)
                                    if json_match:
                                        try: args = json.loads(json_match.group(1))
                                        except: pass
                            tool_calls.append({
                                "id": f"call_{uuid.uuid4().hex[:8]}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(args)}
                            })

                if tool_calls:
                    if self._is_cancelled:
                        self.finished.emit("[Query Stopped by User]")
                        return
                    
                    content = message.get("content", "")
                    if content and content.strip():
                        # Emit partial content so it shows in UI immediately
                        self.partial_response.emit(content)
                        
                    history_message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
                    self.messages.append(history_message)
                    
                    collected_images = []
                    for tool_call in tool_calls:
                        if self._is_cancelled:
                            break
                        tool_name = tool_call["function"]["name"]
                        tool_args_raw = tool_call["function"]["arguments"]
                        tool_args = json.loads(tool_args_raw) if isinstance(tool_args_raw, str) else tool_args_raw
                        
                        status_msg = f"Running tool: {tool_name}..."
                        self.tool_call_started.emit(status_msg)
                        try:
                            tool_result = self.mcp_server.execute_tool(tool_name, tool_args)
                            self.tool_call_finished.emit(status_msg)
                            
                            image_data = None
                            if isinstance(tool_result, dict) and "base64" in tool_result:
                                # Extract image data for multimodal support
                                if len(tool_result["base64"]) > 1000000: # 1MB limit for safety
                                    tool_result["base64"] = tool_result["base64"][:1000000] + "... [TRUNCATED]"
                                    self.tool_call_started.emit("Tool image truncated for stability.")
                                image_data = tool_result.pop("base64")
                                if image_data:
                                    collected_images.append((tool_name, image_data))
                            
                            # Prepare content: either a string (OpenAI-standard) or a list (multimodal)
                            tool_content = json.dumps(tool_result)
                            if len(tool_content) > 400000:
                                tool_content = tool_content[:400000] + "... [TRUNCATED]"
                            
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": tool_name,
                                "content": tool_content
                            })
                                
                        except Exception as e:
                            import traceback
                            print(f"[LLMWorker] Tool Error: {str(e)}\n{traceback.format_exc()}")
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": tool_name,
                                "content": json.dumps({"error": str(e)})
                            })
                    
                    # After all tool results are added, append collected images as a single user message
                    # This maintains tool-call order and provides the visual context.
                    if collected_images:
                        user_content = []
                        for tname, idata in collected_images:
                            user_content.append({"type": "text", "text": f"[Visual Result from {tname}]"})
                            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{idata}"}})
                        
                        self.messages.append({
                            "role": "user",
                            "content": user_content
                        })
                        self.has_image = True
                    
                    payload["messages"] = self.messages
                    payload["tool_choice"] = "auto"
                    continue
                
                content = message.get("content", "")
                self.finished.emit(content)
                break
            if iteration >= max_iterations: self.error.emit(f"Max tool iterations reached.")
        except Exception as e: self.error.emit(str(e))
        finally: 
            if self.session:
                self.session.close()
                self.session = None

class AIChatDialog(QDialog):
    """
    Non-modal AI Assistant dialog with chat sessions and context management.
    """
    def __init__(self, main_window, mcp_server):
        super().__init__(main_window)
        self.main_window = main_window
        self.mcp_server = mcp_server
        
        self.setWindowTitle("Artefakt AI Assistant")
        self.resize(950, 850)
        self.setModal(False)
        
        self.sessions_file = os.path.join("data", "ai_chat_sessions.json")
        os.makedirs("data", exist_ok=True)
        self.sessions = self.load_sessions_from_file()
        self.current_session_id = None
        
        DialogStyles.apply_to_dialog(self)
        
        # Migration: If the prompt is missing the latest protocol instructions, update it
        current_prompt = self.main_window.settings_model.get_value("ai_system_prompt")
        if "INTERNAL TOOLS" not in current_prompt:
            # It's an old version, force update to the new default
            new_default = self.main_window.settings_model.defaults.get("ai_system_prompt")
            self.main_window.settings.setValue("ai_system_prompt", new_default)
            self.system_prompt = new_default
        else:
            self.system_prompt = current_prompt

        self.messages = [{"role": "system", "content": self.system_prompt}]
        self._worker_active = False
        
        self.setup_ui()
        self.load_latest_session_or_new()
        
    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1) # Small margin for window border visibility
        main_layout.setSpacing(0)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- Left Side: Sessions ---
        self.session_panel = QWidget()
        self.session_panel.setMinimumWidth(180)
        self.session_panel.setStyleSheet(f"QWidget {{ background-color: {COLORS.BG_SIDEBAR if hasattr(COLORS, 'BG_SIDEBAR') else '#1A022A'}; border-right: 1px solid {COLORS.BORDER_HOVER}; }}")
        session_layout = QVBoxLayout(self.session_panel)
        session_layout.setContentsMargins(10, 15, 10, 15)
        
        session_header = QLabel("Chat Sessions")
        session_header.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        session_layout.addWidget(session_header)
        
        self.new_chat_btn = QPushButton("+ New Chat")
        self.new_chat_btn.setAutoDefault(False)
        self.new_chat_btn.setStyleSheet(ButtonStyles.primary("small"))
        self.new_chat_btn.clicked.connect(self.new_session)
        session_layout.addWidget(self.new_chat_btn)
        
        self.session_list = QListWidget()
        self.session_list.setStyleSheet(f"QListWidget {{ background: transparent; border: none; color: {COLORS.TEXT_SECONDARY}; outline: none; }} QListWidget::item {{ padding: 10px; border-radius: 6px; margin-bottom: 2px; }} QListWidget::item:selected {{ background-color: {COLORS.PRIMARY_SUBTLE}; color: {COLORS.TEXT_PRIMARY}; border-left: 3px solid {COLORS.PRIMARY}; }} QListWidget::item:hover:!selected {{ background-color: {COLORS.BG_ELEVATED}; }}")
        self.session_list.itemClicked.connect(self.on_session_clicked)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.show_session_context_menu)
        session_layout.addWidget(self.session_list)
        
        # --- Right Side: Chat ---
        right_panel = QWidget()
        layout = QVBoxLayout(right_panel)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"QTabWidget::pane {{ border: 1px solid rgba(255, 255, 255, 0.1); background: #141424; border-radius: 8px; }} QTabBar::tab {{ background: #1A1A2E; color: #A0A0B0; padding: 10px 20px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }} QTabBar::tab:selected {{ background: #6C5CE7; color: white; font-weight: bold; }}")
        
        self.chat_tab = QWidget()
        chat_layout = QVBoxLayout(self.chat_tab)
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setFont(QFont("Segoe UI", 10))
        self.chat_history.setStyleSheet(f"QTextEdit {{ background-color: {COLORS.BG_DARK}; border: 1px solid {COLORS.BORDER_HOVER}; border-radius: 8px; padding: 10px; color: {COLORS.TEXT_PRIMARY}; }} h1, h2, h3, h4, h5, h6 {{ margin-top: 15px; margin-bottom: 5px; color: {COLORS.PRIMARY_LIGHT}; border: none; }} hr {{ height: 1px; border: none; background-color: {COLORS.BORDER_HOVER}; margin: 15px 0; }} p {{ margin-bottom: 5px; }}")
        chat_layout.addWidget(self.chat_history)
        
        input_container = QFrame()
        input_container.setStyleSheet(f"QFrame {{ background-color: {COLORS.BG_ELEVATED}; border-radius: 10px; border: 1px solid {COLORS.BORDER_HOVER}; }}")
        input_main_layout = QVBoxLayout(input_container)
        input_main_layout.setContentsMargins(10, 8, 10, 8)
        input_main_layout.setSpacing(5)
        
        # Row 1: Options and Actions
        top_row_layout = QHBoxLayout()
        self.attach_graph_cb = QCheckBox("Attach Graph")
        self.attach_graph_cb.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 11px;")
        self.graph_source_combo = QComboBox()
        self.graph_source_combo.addItems(["Dashboard Graph", "Graphs Tab"])
        self.graph_source_combo.setStyleSheet(f"QComboBox {{ background: {COLORS.BG_CARD}; border: 1px solid {COLORS.BORDER_DEFAULT}; border-radius: 4px; color: {COLORS.TEXT_SECONDARY}; font-size: 10px; padding: 2px 5px; }} QComboBox::drop-down {{ border: none; }}")
        
        self.clear_btn = QPushButton("New Chat")
        self.clear_btn.setFixedWidth(80)
        self.clear_btn.setAutoDefault(False)
        self.clear_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.clear_btn.clicked.connect(self.new_session)
        
        top_row_layout.addWidget(self.attach_graph_cb)
        top_row_layout.addWidget(self.graph_source_combo)
        top_row_layout.addStretch()
        top_row_layout.addWidget(self.clear_btn)
        
        # Row 2: Input and Send
        bottom_row_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask about your data...")
        self.input_field.setStyleSheet(InputStyles.default() + "border: none; background: transparent;")
        self.input_field.returnPressed.connect(self.handle_send_click)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedWidth(80)
        self.send_btn.setAutoDefault(False)
        self.send_btn.setStyleSheet(ButtonStyles.primary("small"))
        self.send_btn.clicked.connect(self.handle_send_click)
        
        bottom_row_layout.addWidget(self.input_field)
        bottom_row_layout.addWidget(self.send_btn)
        
        input_main_layout.addLayout(top_row_layout)
        input_main_layout.addLayout(bottom_row_layout)
        chat_layout.addWidget(input_container)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-style: italic; font-size: 11px;")
        chat_layout.addWidget(self.status_label)
        
        # --- Tab 2: Context ---
        self.context_tab = QWidget()
        context_scroll = QScrollArea()
        context_scroll.setWidgetResizable(True)
        context_scroll.setStyleSheet("background: transparent; border: none;")
        context_content = QWidget()
        context_content.setStyleSheet(f"background-color: {COLORS.BG_DARK};")
        context_layout = QVBoxLayout(context_content)
        
        settings_group = QGroupBox("API Configuration")
        settings_group.setStyleSheet(GroupBoxStyles.default())
        settings_grid = QGridLayout(settings_group)
        self.url_edit = QLineEdit(self.main_window.settings_model.get_value("ai_url", "http://localhost:1234/v1/chat/completions"))
        self.model_edit = QLineEdit(self.main_window.settings_model.get_value("ai_model", "local-model"))
        self.key_edit = QLineEdit(self.main_window.settings_model.get_value("ai_api_key", "lm-studio"))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setValue(int(self.main_window.settings_model.get_value("ai_timeout", 300)))
        
        self.iterations_spin = QSpinBox()
        self.iterations_spin.setRange(1, 100)
        self.iterations_spin.setValue(int(self.main_window.settings_model.get_value("ai_max_tool_iterations", 25)))
        
        # Explicitly apply input styles to ensure visibility
        input_style = f"QLineEdit, QSpinBox {{ background-color: {COLORS.BG_INPUT}; border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 4px; padding: 6px; color: {COLORS.TEXT_PRIMARY}; }}"
        self.url_edit.setStyleSheet(input_style)
        self.model_edit.setStyleSheet(input_style)
        self.key_edit.setStyleSheet(input_style)
        self.timeout_spin.setStyleSheet(input_style)
        self.iterations_spin.setStyleSheet(input_style)
        
        settings_grid.addWidget(QLabel("API URL:"), 0, 0)
        settings_grid.addWidget(self.url_edit, 0, 1)
        settings_grid.addWidget(QLabel("Model ID:"), 1, 0)
        settings_grid.addWidget(self.model_edit, 1, 1)
        settings_grid.addWidget(QLabel("API Key:"), 2, 0)
        settings_grid.addWidget(self.key_edit, 2, 1)
        settings_grid.addWidget(QLabel("Timeout:"), 3, 0)
        settings_grid.addWidget(self.timeout_spin, 3, 1)
        settings_grid.addWidget(QLabel("Max Iterations:"), 4, 0)
        settings_grid.addWidget(self.iterations_spin, 4, 1)
        
        settings_grid.addWidget(QLabel("Max Image Width:"), 5, 0)
        self.max_width_spin = QSpinBox()
        self.max_width_spin.setRange(256, 3840)
        self.max_width_spin.setValue(int(self.main_window.settings_model.get_value("ai_max_image_width", 1280)))
        self.max_width_spin.setStyleSheet(input_style)
        settings_grid.addWidget(self.max_width_spin, 5, 1)
        
        settings_grid.addWidget(QLabel("JPEG Quality:"), 6, 0)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(10, 100)
        self.quality_spin.setValue(int(self.main_window.settings_model.get_value("ai_image_quality", 80)))
        self.quality_spin.setStyleSheet(input_style)
        settings_grid.addWidget(self.quality_spin, 6, 1)
        
        context_layout.addWidget(settings_group)
        
        tools_group = QGroupBox("AI Permissions & Data Access")
        tools_group.setStyleSheet(GroupBoxStyles.default())
        tools_layout = QVBoxLayout(tools_group)
        tools_layout.setSpacing(2)
        
        # Categorized permissions using a more compact grid or categorized view
        # Category: Data & Core
        core_box = CollapsibleBox("Core Data Access")
        core_layout = QVBoxLayout()
        self.allow_sensors_cb = self._create_perm_cb("Allow Sensor Data", "ai_allow_sensor_data")
        self.allow_notes_cb = self._create_perm_cb("Allow Notes Access", "ai_allow_notes")
        core_layout.addWidget(self.allow_sensors_cb)
        core_layout.addWidget(self.allow_notes_cb)
        core_box.setContentLayout(core_layout)
        tools_layout.addWidget(core_box)
        
        # Category: Control & Projects
        control_box = CollapsibleBox("Control & Management")
        control_layout = QVBoxLayout()
        self.allow_automation_cb = self._create_perm_cb("Allow Automation Control", "ai_allow_automation")
        self.allow_projects_cb = self._create_perm_cb("Allow Project Management", "ai_allow_projects")
        self.allow_config_cb = self._create_perm_cb("Allow Config/Plugin Changes", "ai_allow_config")
        control_layout.addWidget(self.allow_automation_cb)
        control_layout.addWidget(self.allow_projects_cb)
        control_layout.addWidget(self.allow_config_cb)
        control_box.setContentLayout(control_layout)
        tools_layout.addWidget(control_box)
        
        # Category: Vision
        vision_box = CollapsibleBox("Vision & Analysis")
        vision_layout = QVBoxLayout()
        self.allow_vision_cb = self._create_perm_cb("Allow Vision/Graph Analysis", "ai_allow_vision")
        vision_layout.addWidget(self.allow_vision_cb)
        vision_box.setContentLayout(vision_layout)
        tools_layout.addWidget(vision_box)
        
        # Initially expand them for better visibility
        core_box.toggle_button.click()
        control_box.toggle_button.click()
        vision_box.toggle_button.click()
        
        context_layout.addWidget(tools_group)
        
        advanced_group = QGroupBox("Advanced Context")
        advanced_group.setStyleSheet(GroupBoxStyles.default())
        advanced_layout = QVBoxLayout(advanced_group)
        self.prompt_box = CollapsibleBox("System Prompt Editor")
        p_inner = QVBoxLayout()
        self.system_prompt_edit = QTextEdit()
        self.system_prompt_edit.setFixedHeight(200)
        self.system_prompt_edit.setPlainText(self.messages[0]["content"])
        self.system_prompt_edit.setStyleSheet(f"background-color: {COLORS.BG_INPUT}; color: {COLORS.TEXT_PRIMARY}; border-radius: 4px;")
        p_inner.addWidget(self.system_prompt_edit)
        
        prompt_btn_layout = QHBoxLayout()
        self.save_context_btn = QPushButton("Save New Context")
        self.save_context_btn.setAutoDefault(False)
        self.save_context_btn.setStyleSheet(ButtonStyles.primary("small"))
        self.save_context_btn.clicked.connect(self.save_new_context)
        
        self.reset_context_btn = QPushButton("Reset to Original Context")
        self.reset_context_btn.setAutoDefault(False)
        self.reset_context_btn.setStyleSheet(ButtonStyles.secondary("small"))
        self.reset_context_btn.clicked.connect(self.reset_to_original_context)
        
        prompt_btn_layout.addWidget(self.save_context_btn)
        prompt_btn_layout.addWidget(self.reset_context_btn)
        p_inner.addLayout(prompt_btn_layout)
        
        self.prompt_box.setContentLayout(p_inner)
        advanced_layout.addWidget(self.prompt_box)
        
        self.history_box = CollapsibleBox("Raw History (JSON)")
        h_inner = QVBoxLayout()
        self.history_json_edit = QTextEdit()
        self.history_json_edit.setFixedHeight(300)
        self.history_json_edit.setStyleSheet(f"background-color: {COLORS.BG_INPUT}; color: {COLORS.TEXT_PRIMARY}; border-radius: 4px;")
        h_inner.addWidget(self.history_json_edit)
        self.history_box.setContentLayout(h_inner)
        advanced_layout.addWidget(self.history_box)
        
        apply_context_btn = QPushButton("Apply Context Changes")
        apply_context_btn.setAutoDefault(False)
        apply_context_btn.setStyleSheet(ButtonStyles.secondary("small"))
        apply_context_btn.clicked.connect(self.apply_context_changes)
        advanced_layout.addWidget(apply_context_btn)
        context_layout.addWidget(advanced_group)
        
        save_settings_btn = QPushButton("Save Settings")
        save_settings_btn.setAutoDefault(False)
        save_settings_btn.setStyleSheet(ButtonStyles.primary("medium"))
        save_settings_btn.clicked.connect(self.save_settings)
        context_layout.addWidget(save_settings_btn)
        
        # Add a spacer to push everything up
        context_layout.addStretch()
        
        context_scroll.setWidget(context_content)
        QVBoxLayout(self.context_tab).addWidget(context_scroll)
        
        self.tabs.addTab(self.chat_tab, "💬 Chat")
        self.tabs.addTab(self.context_tab, "⚙️ Settings")
        layout.addWidget(self.tabs)
        
        self.splitter.addWidget(self.session_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 730])
        main_layout.addWidget(self.splitter)
        self.update_history_json()

    # --- Session Management ---
    def load_sessions_from_file(self):
        if os.path.exists(self.sessions_file):
            try:
                with open(self.sessions_file, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return []

    def save_sessions_to_file(self):
        try:
            with open(self.sessions_file, 'w', encoding='utf-8') as f: json.dump(self.sessions, f, indent=2)
        except: pass

    def load_latest_session_or_new(self):
        self.update_session_list_ui()
        if self.sessions:
            self.load_session(self.sessions[0]["id"])
            self.session_list.setCurrentRow(0)
        else: self.new_session()

    def update_session_list_ui(self):
        self.session_list.clear()
        # Sort by updated_at (descending), fallback to name
        self.sessions.sort(key=lambda x: x.get("updated_at", x.get("name", "")), reverse=True)
        for s in self.sessions:
            item = QListWidgetItem(s["name"])
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.session_list.addItem(item)

    def load_session(self, sid):
        if self.current_session_id: self.save_current_session_state()
        self.current_session_id = sid
        s = next((x for x in self.sessions if x["id"] == sid), None)
        if s:
            self.messages = s.get("messages", [])
            if not self.messages or self.messages[0]["role"] != "system":
                self.messages.insert(0, {"role": "system", "content": self.system_prompt})
            self.rebuild_chat_ui_from_history()
            self.update_history_json()
            if hasattr(self, 'system_prompt_edit'): self.system_prompt_edit.setPlainText(self.messages[0]["content"])

    def save_current_session_state(self):
        if self.current_session_id:
            for s in self.sessions:
                if s["id"] == self.current_session_id:
                    s["messages"] = self.messages
                    s["updated_at"] = datetime.now().isoformat()
                    break
            self.save_sessions_to_file()

    def new_session(self):
        if self.current_session_id: self.save_current_session_state()
        sid = str(uuid.uuid4())
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        iso_now = datetime.now().isoformat()
        new_s = {
            "id": sid, 
            "name": now_str, 
            "messages": [{"role": "system", "content": self.system_prompt}],
            "updated_at": iso_now
        }
        self.sessions.insert(0, new_s)
        self.current_session_id = sid
        self.messages = new_s["messages"]
        self.stop_query()
        self.update_session_list_ui()
        self.session_list.setCurrentRow(0)
        self.chat_history.clear()
        self.chat_history.setHtml(f"<div style='color: {COLORS.TEXT_SECONDARY};'>New session started.</div>")
        self.update_history_json()
        if hasattr(self, 'system_prompt_edit'): self.system_prompt_edit.setPlainText(self.messages[0]["content"])
        self.save_sessions_to_file()

    def on_session_clicked(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid != self.current_session_id: self.load_session(sid)

    def show_session_context_menu(self, pos):
        item = self.session_list.itemAt(pos)
        if not item: return
        menu = QMenu()
        
        rename_action = QAction("Rename Session", self)
        rename_action.triggered.connect(lambda: self.rename_session(item))
        menu.addAction(rename_action)
        
        delete_action = QAction("Delete Session", self)
        delete_action.triggered.connect(lambda: self.delete_session(item))
        menu.addAction(delete_action)
        
        menu.exec(self.session_list.mapToGlobal(pos))

    def rename_session(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        old_name = item.text()
        new_name, ok = QInputDialog.getText(self, "Rename Session", "Enter new name for the session:", text=old_name)
        if ok and new_name.strip():
            new_name = new_name.strip()
            for s in self.sessions:
                if s["id"] == sid:
                    s["name"] = new_name
                    s["updated_at"] = datetime.now().isoformat()
                    break
            self.save_sessions_to_file()
            self.update_session_list_ui()
            # Restore selection
            for i in range(self.session_list.count()):
                if self.session_list.item(i).data(Qt.ItemDataRole.UserRole) == sid:
                    self.session_list.setCurrentRow(i)
                    break

    def delete_session(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        self.sessions = [s for s in self.sessions if s["id"] != sid]
        self.save_sessions_to_file()
        self.update_session_list_ui()
        if sid == self.current_session_id:
            self.current_session_id = None
            self.load_latest_session_or_new()

    def rebuild_chat_ui_from_history(self):
        self.chat_history.clear()
        for msg in self.messages:
            if msg["role"] == "system": continue
            role, content = msg["role"], msg.get("content", "")
            cursor = self.chat_history.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            
            if role == "user":
                cursor.insertHtml("<hr>")
                text = ""
                images = []
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            text += part.get("text", "")
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url: images.append(url)
                else:
                    text = content
                
                cursor.insertHtml(f"<div style='color: {COLORS.PRIMARY_LIGHT}; margin-bottom: 10px;'><b>You:</b> {html.escape(text)}</div>")
                for img_url in images:
                    # Scale images for UI display
                    cursor.insertHtml(f"<br><img src='{img_url}' width='450'><br>")
                cursor.insertHtml("<br>")
                
            elif role == "assistant":
                # Scrub thoughts from history display
                display_content = self.scrub_thoughts(content)
                tool_calls = msg.get("tool_calls", [])
                
                if not display_content and not tool_calls:
                    continue
                
                cursor.insertHtml(f"<div style='margin-top: 10px; margin-bottom: 5px;'><b>AI:</b></div>")
                if display_content:
                    cursor.insertMarkdown(display_content)
                
                for tc in tool_calls:
                    f = tc.get("function", {})
                    name = f.get("name", "unknown")
                    cursor.insertHtml(f"<div style='color: {COLORS.INFO}; font-style: italic; margin-left: 15px; margin-top: 2px;'>🔧 Tool Call: <b>{name}</b></div><br>")
                
                cursor.insertHtml("<br>")
                
            elif role == "tool":
                # We don't display tool messages in the chat history to keep it clean for the user.
                # The user only sees the final assistant response.
                continue
        self.chat_history.moveCursor(QTextCursor.MoveOperation.End)

    def handle_send_click(self):
        if self.send_btn.text() == "Stop": self.stop_query()
        else: self.send_message()

    def stop_query(self):
        if not getattr(self, '_worker_active', False):
            self.status_label.setText("")
            self.set_ui_enabled(True)
            return

        self.status_label.setText("Stopping AI Assistant...")
        
        if hasattr(self, 'worker') and self.worker:
            try:
                self.worker.finished.disconnect()
                self.worker.error.disconnect()
                self.worker.partial_response.disconnect()
                self.worker.tool_call_started.disconnect()
                self.worker.tool_call_finished.disconnect()
            except Exception:
                pass
            self.worker.cancel()
        
        if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            if not self.worker_thread.wait(5000):
                print("[AIChat] Worker thread did not stop gracefully, terminating.")
                self.worker_thread.terminate()
                self.worker_thread.wait(1000)
        
        self._worker_active = False
        self.status_label.setText("")
        self.set_ui_enabled(True)

    def update_history_json(self):
        self.history_json_edit.setPlainText(json.dumps(self.messages, indent=2))

    def apply_context_changes(self):
        try:
            self.messages = json.loads(self.history_json_edit.toPlainText())
            self.save_current_session_state()
            self.chat_history.append("<i>Context updated.</i>")
        except Exception as e: self.chat_history.append(f"<i>Error: {e}</i>")

    def save_new_context(self):
        new_prompt = self.system_prompt_edit.toPlainText().strip()
        if new_prompt:
            self.main_window.settings.setValue("ai_system_prompt", new_prompt)
            # Also update current messages if the first one is system
            if self.messages and self.messages[0]["role"] == "system":
                self.messages[0]["content"] = new_prompt
                self.update_history_json()
                self.save_current_session_state()
            self.chat_history.append("<i>System prompt saved as default.</i>")

    def reset_to_original_context(self):
        # Original context from settings model defaults
        default_prompt = self.main_window.settings_model.defaults.get("ai_system_prompt", "")
        self.system_prompt_edit.setPlainText(default_prompt)
        self.chat_history.append("<i>Context reset to original default (not saved yet).</i>")

    def _create_perm_cb(self, label, setting_key):
        cb = QCheckBox(label)
        cb.setChecked(self.main_window.settings_model.get_bool(setting_key, True))
        cb.setStyleSheet(f"color: {COLORS.TEXT_PRIMARY}; font-size: 11px; padding: 2px;")
        return cb

    def save_settings(self):
        self.main_window.settings.setValue("ai_url", self.url_edit.text())
        self.main_window.settings.setValue("ai_model", self.model_edit.text())
        self.main_window.settings.setValue("ai_api_key", self.key_edit.text())
        self.main_window.settings.setValue("ai_timeout", self.timeout_spin.value())
        self.main_window.settings.setValue("ai_max_tool_iterations", self.iterations_spin.value())
        self.main_window.settings.setValue("ai_max_image_width", self.max_width_spin.value())
        self.main_window.settings.setValue("ai_image_quality", self.quality_spin.value())
        
        # Save permissions
        perm_map = {
            "ai_allow_sensor_data": self.allow_sensors_cb.isChecked(),
            "ai_allow_notes": self.allow_notes_cb.isChecked(),
            "ai_allow_automation": self.allow_automation_cb.isChecked(),
            "ai_allow_vision": self.allow_vision_cb.isChecked(),
            "ai_allow_projects": self.allow_projects_cb.isChecked(),
            "ai_allow_config": self.allow_config_cb.isChecked()
        }
        for key, val in perm_map.items():
            self.main_window.settings.setValue(key, "true" if val else "false")
            
        self.chat_history.append("<i>Settings saved.</i>")

    def send_message(self):
        if getattr(self, '_worker_active', False):
            return

        text = self.input_field.text().strip()
        if not text: return
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.chat_history.toPlainText().strip() == "": cursor.insertHtml("<hr>")
        cursor.insertHtml(f"<div style='color: {COLORS.PRIMARY_LIGHT}; margin-bottom: 10px;'><b>You:</b> {html.escape(text)}</div><br>")
        
        content = text
        if self.attach_graph_cb.isChecked():
            source = "dashboard" if self.graph_source_combo.currentIndex() == 0 else "graphs_tab"
            shot = self.mcp_server.get_graph_screenshot(source)
            if "base64" in shot:
                img_url = f"data:image/jpeg;base64,{shot['base64']}"
                content = [{"type": "text", "text": f"[Attached: {source}] {text}"}, {"type": "image_url", "image_url": {"url": img_url}}]
                cursor.insertHtml(f"<div style='color: {COLORS.SUCCESS}; font-size: 11px;'><i>[{html.escape(source)} Attached]</i></div>")
                cursor.insertHtml(f"<br><img src='{img_url}' width='450'><br>")
        
        self.messages.append({"role": "user", "content": content})
        
        self.update_history_json()
        self.save_current_session_state()
        self.input_field.clear()
        self.attach_graph_cb.setChecked(False)
        self._worker_active = True
        self.set_ui_enabled(False)
        self.status_label.setText("AI is thinking...")
        
        config = {
            "url": self.url_edit.text(),
            "model": self.model_edit.text(),
            "api_key": self.key_edit.text(),
            "timeout": self.timeout_spin.value(),
            "max_iterations": self.iterations_spin.value()
        }
        tools = [{"type": "function", "function": t} for t in self.mcp_server.list_tools()]
        
        self.worker_thread = QThread()
        self.worker = LLMWorker(config, self.messages, tools, self.mcp_server)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_llm_finished)
        self.worker.error.connect(self.on_llm_error)
        self.worker.partial_response.connect(self.on_partial_response)
        self.worker.tool_call_started.connect(self.on_tool_call)
        self.worker.tool_call_finished.connect(self.on_tool_call_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.worker_thread.quit)
        self.worker_thread.start()

    def set_ui_enabled(self, e):
        self.input_field.setEnabled(e)
        self.clear_btn.setEnabled(e)
        self.send_btn.setText("Send" if e else "Stop")
        self.send_btn.setStyleSheet(ButtonStyles.primary("small") if e else ButtonStyles.secondary("small"))
        if e: self.input_field.setFocus()

    def scrub_thoughts(self, text):
        """Removes <think>, <thinking>, or <thought> tags and their content."""
        if not text:
            return ""
        if not isinstance(text, str):
            return str(text)
        text = re.sub(r'<(think|thinking|thought)>[\s\S]*?<\/\1>', '', text)
        text = re.sub(r'<(think|thinking|thought)>[\s\S]*$', '', text)
        return text.strip()

    @pyqtSlot(str)
    def on_llm_finished(self, text):
        self._worker_active = False
        self.status_label.setText("")
        
        # Scrub <think>, <thinking>, <thought> tags
        text = self.scrub_thoughts(text)
        
        if text and text.strip():
            self.messages.append({"role": "assistant", "content": text})
            self.update_history_json()
            self.save_current_session_state()
            
        # Always rebuild to ensure UI is in sync with history
        self.rebuild_chat_ui_from_history()
        self.set_ui_enabled(True)
        self.chat_history.moveCursor(QTextCursor.MoveOperation.End)

    @pyqtSlot(str)
    def on_partial_response(self, text):
        """Displays text content that came with tool calls immediately"""
        text = self.scrub_thoughts(text)
        if text and text.strip():
            self.append_ai_message(text)

    def append_ai_message(self, text):
        """Helper to append an AI message to the chat history UI"""
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml("<div style='margin-top: 10px; margin-bottom: 5px;'><b>AI:</b></div>")
        cursor.insertMarkdown(text)
        cursor.insertHtml("<br>")
        self.chat_history.moveCursor(QTextCursor.MoveOperation.End)

    @pyqtSlot(str)
    def on_llm_error(self, err):
        self._worker_active = False
        self.status_label.setText("")
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f"<div style='color: {COLORS.ERROR}; margin-top: 10px;'><b>Error:</b> {html.escape(err)}</div><br>")
        self.set_ui_enabled(True)

    @pyqtSlot(str)
    def on_tool_call(self, text):
        self.status_label.setText(text)
        
        # Display the tool call in the chat history real-time
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(f"<div style='color: {COLORS.INFO}; font-style: italic; margin-left: 15px; margin-top: 2px;'>🔧 {text}</div><br>")
        self.chat_history.moveCursor(QTextCursor.MoveOperation.End)

    @pyqtSlot(str)
    def on_tool_call_finished(self, start_msg):
        self.status_label.setText(f"AI is processing result...")
        # We no longer update the chat history with tool results

    def closeEvent(self, event):
        self.stop_query()
        super().closeEvent(event)
