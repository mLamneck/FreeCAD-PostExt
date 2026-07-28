# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

try:
	import FreeCAD # type: ignore[import-not-found]
	import json
	from . import utils
	from .post_properties import Properties
	from .wrappers import CamOperations

# =============================================================================
# Gui - Post Processor Dialog Window
# =============================================================================

	#FreeCAD switched to Qt6 in later releases
	try:
		from PySide6 import QtWidgets, QtCore # type: ignore[import-not-found]
	except ImportError:
		from PySide2 import QtWidgets, QtCore # type: ignore[import-not-found]
	import os


# -----------------------------------------------------------------------------
# Gui - CollapsibleGroupBox
# -----------------------------------------------------------------------------

	class CollapsibleGroupBox(QtWidgets.QWidget):# type: ignore[misc, reportUnknownMemberType]
		def __init__(self, title : str ="", parent : object = None):
			super().__init__(parent)

			# --- Toggle Button (Header) ---
			self.toggle_button = QtWidgets.QToolButton(text=title)
			self.toggle_button.setCheckable(True)
			self.toggle_button.setChecked(True)
			self.toggle_button.setArrowType(QtCore.Qt.DownArrow)
			self.toggle_button.setToolButtonStyle(
				QtCore.Qt.ToolButtonTextBesideIcon
			)
			self.toggle_button.setAutoRaise(True)
			self.toggle_button.setSizePolicy(
				QtWidgets.QSizePolicy.Expanding,
				QtWidgets.QSizePolicy.Fixed
			)
			self.toggle_button.clicked.connect(self.toggle_content)

			self.toggle_button.setStyleSheet("""
				QToolButton {
					border: none;
					font-weight: bold;
					text-align: left;
					padding: 6px;
				}
				QToolButton:hover {
					background: rgba(0, 0, 0, 20);
				}
			""")

			self.content_area = QtWidgets.QWidget()
			self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
			self.content_layout.setContentsMargins(20, 4, 4, 4)
			self.content_layout.setSpacing(6)
			main_layout = QtWidgets.QVBoxLayout(self)
			main_layout.setContentsMargins(0, 0, 0, 0)
			main_layout.setSpacing(0)
			main_layout.addWidget(self.toggle_button)
			main_layout.addWidget(self.content_area)

		def toggle_content(self):
			expanded = self.toggle_button.isChecked()
			self.content_area.setVisible(expanded)
			self.toggle_button.setArrowType(
				QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow
			)

		def layout(self):
			"""Expose inner layout for adding widgets"""
			return self.content_layout

# -----------------------------------------------------------------------------
# Gui - Post Processor Dialog Window
# -----------------------------------------------------------------------------

	class SettingsDialog(QtWidgets.QDialog):
		def __init__(self, _properties : Properties, _operations : CamOperations, _post):
				super().__init__(None)

				self._properties : Properties = _properties
				self._operations = _operations

				# =============== Infos from Post ===============
				self._file_ending = getattr(_post,"FILE_ENDING","nc")
				_name = getattr(_post,"POST_NAME","UNNAMED")
				self._job = _post.JOB
				self._global_param_store = FreeCAD.ParamGet(f"User parameter:BaseApp/Preferences/CAM/POSTS/{_name}/")
				self._project_properties_group_name = f"PostProcessor"
				self._project_properties_name = f"Properties_{_name}"

				self.setWindowTitle("Postprocessor Settings")
				self.resize(1000, 400)

				# =============== Build Layout ===============

				main_layout = QtWidgets.QVBoxLayout(self)

				# === Tabs ===
				#tabs = QtWidgets.QTabWidget()
				#tabs.tabBar().setExpanding(False)  # wichtig!
				#tabs.setDocumentMode(True)  # optional, für besseres Aussehen

				#main_layout.addWidget(tabs)

				# Settings Tab
				self.settings_tab = QtWidgets.QWidget()
				#tabs.addTab(self.settings_tab, "Settings")
				main_layout.addWidget(self.settings_tab)
				main_layout.setContentsMargins(0, 0, 10, 10) # left,top,right,bottom
				main_layout.setSpacing(10)  
				self._build_settings_tab(self.settings_tab)

				# === Ok / Cancel ===
				buttons = QtWidgets.QDialogButtonBox(
					QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
				)
				main_layout.addWidget(buttons)

				buttons.accepted.connect(self.accept)
				buttons.rejected.connect(self.reject)
				
				self._load_post_state()

		def _header_label(self,text):
				label = QtWidgets.QLabel(text)
				font = label.font()
				font.setBold(True)
				font.setPointSize(font.pointSize() + 2)
				label.setFont(font)
				label.setContentsMargins(0, 6, 0, 6)
				return label

		def _build_settings_left_column(self, parent):
				left_container = QtWidgets.QWidget()
				left_container.setSizePolicy(
					QtWidgets.QSizePolicy.Expanding,
					QtWidgets.QSizePolicy.Preferred
				)
				#left_container.setFixedWidth(450)
				left_layout = QtWidgets.QVBoxLayout(left_container)
				left_layout.setContentsMargins(12, 12, 12, 12)
				left_layout.setSpacing(5)

				# =============== Program Section ===============

				left_layout.addWidget(self._header_label("Program"))

				# | Filename: | edit			| btn 
				hl = QtWidgets.QHBoxLayout()
				label = QtWidgets.QLabel("Filename:")
				label.setFixedWidth(80)
				self.file_edit = QtWidgets.QLineEdit()
				self.file_edit.textChanged.connect(self._set_filename)
				self.file_button = QtWidgets.QToolButton()
				self.file_button.setText("...")
				self.file_button.setToolTip("Browse for file")
				self.file_button.clicked.connect(self._select_file)
				hl.addWidget(label)
				hl.addWidget(self.file_edit, stretch=1)
				hl.addWidget(self.file_button)
				left_layout.addLayout(hl)

				# | Name:         | edit			| 
				hl = QtWidgets.QHBoxLayout()
				label = QtWidgets.QLabel("Name:")
				label.setFixedWidth(80)
				self.FprogName = QtWidgets.QLineEdit()
				hl.addWidget(label)
				hl.addWidget(self.FprogName, stretch=1)
				left_layout.addLayout(hl)

				# =============== Post Section ===============

				left_layout.addWidget(self._header_label("Post"))

				self.cb_openNcInEditor = QtWidgets.QCheckBox("Open NC in Editor")
				left_layout.addWidget(self.cb_openNcInEditor)

				left_layout.addStretch()

				#save preferences button
				self.btn_savePreference = QtWidgets.QPushButton("Save as preference")
				self.btn_savePreference.clicked.connect(self._save_state_global)
				left_layout.addWidget(self.btn_savePreference)

				#remove properties from cam operations button
				self.btn_remove_properties = QtWidgets.QPushButton("Remove OP Properties")
				self.btn_remove_properties.setToolTip(
					"This will remove the properties added from this POST to your CAM operations"
				)
				self.btn_remove_properties.clicked.connect(self._remove_properties_from_operations)
				left_layout.addWidget(self.btn_remove_properties)

				parent.addWidget(left_container,stretch=1)
				
		def _build_settings_tab(self, parent):
				content_layout = QtWidgets.QHBoxLayout(parent)
				content_layout.setContentsMargins(0, 0, 0, 0)
				content_layout.setSpacing(0)

				# ===== left column =====
				self._build_settings_left_column(content_layout)
				
				# ===== right column =====
				right_container = QtWidgets.QWidget()
				right_container.setMinimumWidth(400)
				right_container.setObjectName("settingsRightPane")
				right_container.setStyleSheet("""
				QWidget#settingsRightPane {
					background-color: palette(base);
					border-left: 1px solid palette(mid);
				}
				""")

				right_layout = QtWidgets.QVBoxLayout(right_container)
				right_layout.setContentsMargins(12, 12, 12, 12)
				self._add_dynamic_properties(right_layout)
				content_layout.addWidget(right_container, stretch=0)

		def _add_dynamic_properties(self, layout):
				groups = {}
				for key, prop in self._properties.post_propeties:
					gname = prop.group
					if gname not in groups:
						gb = CollapsibleGroupBox(gname,self)

						grid = QtWidgets.QGridLayout()
						grid.setContentsMargins(0, 0, 0, 0)
						grid.setHorizontalSpacing(6)
						grid.setVerticalSpacing(6)

						grid.setColumnStretch(0, 0)
						grid.setColumnStretch(1, 0)
						grid.setColumnStretch(2, 0)

						gb.layout().addLayout(grid)
						layout.addWidget(gb)

						groups[gname] = grid

				self.widgets = {}
				for key, prop in self._properties.post_propeties:
					grid = groups[prop.group]
					row = grid.rowCount()

					widget = prop.widget
					if prop.hint:
						widget.setToolTip(prop.hint)

					self.widgets[key] = widget

					label = QtWidgets.QLabel(prop.label)
					label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
					label.setWordWrap(True)
					grid.addWidget(label,  row, 0)
					grid.addWidget(widget, row, 2)

		"""
		def _build_operations_tab(self):
				layout = QtWidgets.QVBoxLayout(self.operations_tab)

				operations = self.operations.getMachiningOperations()

				self.table = QtWidgets.QTableWidget(len(operations), 4)
				self.table.setHorizontalHeaderLabels([
					"Operation", "HSpeed", "VSpeed", "RSpeed"
				])
				self.table.verticalHeader().setVisible(False)
				self.table.setAlternatingRowColors(True)

				# Spaltenbreiten
				self.table.setColumnWidth(0, 180)
				for col in (1, 2, 3):
					self.table.setColumnWidth(col, 80)

				for row, obj in enumerate(operations):
					# Operation Name
					item = QtWidgets.QTableWidgetItem(obj.label())
					item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
					self.table.setItem(row, 0, item)

					# Speed-Spalten
					for col in (1, 2, 3):
						spin = TadvancedSpinBox()
						#spin.setFocusPolicy(QtCore.Qt.StrongFocus)
						spin.setRange(100, 10000)
						spin.setValue(2000)
						spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
						spin.setAlignment(QtCore.Qt.AlignRight)
						spin.setFixedWidth(70)

						self.table.setCellWidget(row, col, spin)

				self.table.setFocusPolicy(QtCore.Qt.NoFocus)
				self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

				self.table.setMouseTracking(False)
				self.table.viewport().setMouseTracking(False)

				self.table.setAttribute(QtCore.Qt.WA_Hover, False)
				self.table.viewport().setAttribute(QtCore.Qt.WA_Hover, False)
				self.table.setFocusPolicy(QtCore.Qt.NoFocus)
				self.table.setMouseTracking(False)
				self.table.viewport().setMouseTracking(False)
				self.table.setFocusPolicy(QtCore.Qt.NoFocus)
				self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

				self.table.resizeColumnsToContents()
				self.table.horizontalHeader().setStretchLastSection(True)
				layout.addWidget(self.table)
		"""
		def _curr_state_to_json(self):
				data = {
					"postProperties": self._properties.to_dict(),
					"outFileName": self.file_edit.text(),
					"openNcInEditor" : self.cb_openNcInEditor.isChecked(),
				}
				return json.dumps(data)

		def _restore_state_from_json(self,_jsonStr):
				stateDict = json.loads(_jsonStr)
				self._properties.from_dict(stateDict.get("postProperties",{}))
				self.file_edit.setText(stateDict.get("outFileName",""))
				self.cb_openNcInEditor.setChecked(stateDict.get("openNcInEditor",False))

		def _save_state_global(self):
				self._global_param_store.SetString("globalProperties",self._curr_state_to_json())

		def _load_state_global(self):
				jsonStr = self._global_param_store.GetString("globalProperties","{}")
				self._restore_state_from_json(jsonStr)

		def _save_post_state(self):
				#doc = FreeCAD.ActiveDocument
				doc = self._job
				if not hasattr(doc,self._project_properties_name):
					doc.addProperty(f"App::PropertyString", self._project_properties_name, self._project_properties_group_name, "")
				setattr(doc,self._project_properties_name,self._curr_state_to_json())

		def _load_post_state(self):
				try:
					#doc = FreeCAD.ActiveDocument
					doc = self._job
					if not hasattr(doc,self._project_properties_name):
						doc.addProperty(f"App::PropertyString", self._project_properties_name, self._project_properties_group_name, "")
					self._restore_state_from_json(getattr(doc,self._project_properties_name))
					return
				except:
					pass
				self._load_state_global()

		def _remove_properties_from_operations(self):
				for op in self._operations.getMachiningOperations():
					op.remove_properties()
					#utils.remove_property_group(op.getFcOp(),"PostProcessor")

		def accept(self):
				try:
					self._save_post_state()
				finally:
					super().accept()

		def reject(self):
				try:
					self._save_post_state()
				finally:
					super().reject()

		def _select_file(self):
				fname, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
					self,
					"Select Output File",
					"",
					f"G-Code (*.{self._file_ending});;All Files (*)"
				)

				if not fname:
					return

				if not os.path.splitext(fname)[1]:
					if f"*.{self._file_ending}" in selected_filter:
						fname += f".{self._file_ending}"

				self.file_edit.setText(fname)

		def _set_filename(self, _name):
				self.FprogName.setText(os.path.splitext(os.path.basename(_name))[0])

		@property
		def progname(self):
				return self.FprogName.text()

		@property
		def filename(self):
				return self.file_edit.text()

		@property
		def open_nc_in_editor(self):
				return self.cb_openNcInEditor.isChecked()

except Exception as e:
	raise Exception(f"Import error in gui.py {e}")