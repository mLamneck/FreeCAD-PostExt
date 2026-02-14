# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

from __future__ import annotations

try:
	from typing import NotRequired, TypedDict, List, Literal, Unpack, Dict, Iterator, Tuple

	#FreeCAD switched to Qt6 in later releases
	try:
		from PySide6 import QtWidgets, QtCore # type: ignore[import-not-found]
	except ImportError:
		from PySide2 import QtWidgets, QtCore # type: ignore[import-not-found]


	# =============================================================================
	# Special widget for numeric values
	# =============================================================================

	class AutoFocusSpinBox(QtWidgets.QDoubleSpinBox):
		def focusInEvent(self,event):
			super().focusInEvent(event)
			QtCore.QTimer.singleShot(0, self.lineEdit().selectAll)


	# =============================================================================
	# Property Descriptors
	# =============================================================================

	class PropertyDescrParams(TypedDict):
		"""
		Parameters that will be passed to Property(...) by the user
		"""
		scope : NotRequired[List[Literal["post","op"]]]
		hint: NotRequired[str]
		title: str
		group: NotRequired[str]
		value: NotRequired[str | int | float | bool]
		type : NotRequired[Literal["Integer","Float","Bool","Velocity"]]
		values: NotRequired[List[str]]	#enums

		decimals : NotRequired[int]
		min : NotRequired[float]
		max : NotRequired[float]
		step : NotRequired[float]
		widget_scale : NotRequired[float]

		op_value : NotRequired[float]
		expression : NotRequired[str] 

	class PropertyDescr:
		"""
		Descriptor for a single property.

		Depending on the scope, this descriptor is either instantiated as a GUI element
		in the post dialog, registered as a CAM operation property using FreeCAD's
		property system, or both.
		"""
		def __init__(self, **descr: Unpack[PropertyDescrParams]) -> None:
			self._descr = descr
			self.scope = descr.get("scope",["post"])
			self.hint = descr.get("hint","")
			self.title = descr.get("title")
			self.group = descr.get("group","General")
			self.value = descr.get("value",None)
			self.values = descr.get("values",None)
			if self.values is not None:
				self.type = "Enumeration"
				self.value = descr.get("value",0)
			else:
				propNameMapping = {"bool": "Bool", "int": "Integer", "float": "Float", "list": "Enumeration"}
				self.type = descr.get("type",propNameMapping[type(descr.get("value",0.0)).__name__])

			#widget
			self.decimals = descr.get("decimals",None)
			self.min = descr.get("min",None)
			self.max = descr.get("max",None)
			self.step = descr.get("step",None)
			self.widget_scale = descr.get("widget_scale",1)

			#opertation specific
			self.op_value = descr.get("op_value",None)
			self.expression = descr.get("expression")

		@property
		def is_enum(self):
			return self.values is not None


	# =============================================================================
	# Properties
	# =============================================================================

	class PropertyBase:
		"""
		Base class for all Properties that can be instantiated.
		
		Concrete Property implementations should derive from this class.
		"""
		def __init__(self, descr : PropertyDescr):
			self.is_enum = descr.is_enum
			self._widget_scale : float = descr.widget_scale
			self._label : str = descr.title
			self.def_value = descr.value
			self.values = descr.values
			self.group : str = descr.group
			self.scope = descr.scope
			for s in self.scope:
				if not s in ["post","op"]:
					raise Exception(f'Invalid scope "{s} in property"')
			self.type = descr.type
			self.hint = descr.hint
			self.title = descr.title
			self.setValue(self.def_value)

		def onChange(self):
			pass

		def setValue(self, value):
			return

		def getValue(self) -> float:
			return 0

		@property
		def label(self):
			return self._label

		@property
		def value(self):
			val = self.getValue()
			assert val is not None, f"Value not defined"
			return val

		def __str__(self):
			return str(self.value)

	# -----------------------------------------------------------------------------
	# Property System - type specific property specialization for PP Gui
	# move this section to .gui!?
	# -----------------------------------------------------------------------------

	class PostProperty(PropertyBase):
		def __init__(self, widget, descr : PropertyDescr):
			self._widget = widget
			super().__init__(descr)

		@property
		def widget(self):
			return self._widget
		
	class BoolProperty(PostProperty):
		def __init__(self, descr : PropertyDescr):
			self.checkbox = QtWidgets.QCheckBox()
			super().__init__(self.checkbox,descr)
			
		def getValue(self):
			return self.checkbox.isChecked()

		def setValue(self, value):
			self.checkbox.setChecked(value)

	class NumericProperty(PostProperty):
		def __init__(self, type : Literal["Float","Integer"], descr : PropertyDescr):
			self._Fis_float = type == "Float"

			if self._Fis_float:
				self.spinbox = AutoFocusSpinBox()
				self.spinbox.setDecimals(descr.decimals if descr.decimals is not None else 2)
				self.spinbox.setSingleStep(descr.step if descr.step is not None else 0.1)
			else:
				self.spinbox = AutoFocusSpinBox()
				self.spinbox.setSingleStep(descr.step if descr.step is not None else 1)
				self.spinbox.setDecimals(0)

			self.spinbox.setMinimum(descr.min if descr.min is not None else -1000)
			self.spinbox.setMaximum(descr.max if descr.max is not None else 1000)

			self.spinbox.setFixedWidth(80)
			self.spinbox.valueChanged.connect(self.onChange)

			super().__init__(self.spinbox,descr)

		def getValue(self):
			val = self.spinbox.value()/self._widget_scale
			if self._Fis_float:
				return val
			return int(val)

		def setValue(self, value):
			self.spinbox.setValue(value*self._widget_scale)

	class ComboBoxProperty(PostProperty):
		def __init__(self, descr : PropertyDescr):
			self.combobox = QtWidgets.QComboBox()
			super().__init__(self.combobox,descr)

			self.combobox.addItems(descr.values)
			self.combobox.currentIndexChanged.connect(self.onChange)

		def getValue(self):
			return self.combobox.currentText()

		def setValue(self, value):
			if isinstance(value, str):
				index = self.combobox.findText(value)
				if index >= 0:
					self.combobox.setCurrentIndex(index)

	def instantiate_property_gui(descr : PropertyDescr):
		typ = descr.type
		if typ in ["Bool"]:
			return BoolProperty(descr)
		elif typ in ["Integer"]:
			return NumericProperty("Integer",descr)
		elif typ in ["Float","Velocity"]:
			return NumericProperty("Float",descr)
		elif typ in ["Enumeration"]:
			return ComboBoxProperty(descr)
		else:
			raise Exception(f"type {typ} not supported")

	# -----------------------------------------------------------------------------
	# Property System - added to cam operations with FreeCAD's property system
	# -----------------------------------------------------------------------------

	class OperationProperty(PropertyBase):
		"""
		Property to be added to cam operations using FreeCAD's property system
		"""
		def __init__(self, prop_name : str, descr : PropertyDescr):
			super().__init__(descr)
			self.FcObj = None
			self.expression = descr.expression
			self._name = prop_name
			self.defOpValue = descr.op_value
		
		def install(self, _obj):
			self.FcObj = _obj
			prop_name = self._name
			if not hasattr(self.FcObj,prop_name):
				self.FcObj.addProperty(f"App::Property{self.type}", prop_name, "PostProcessor", self.hint)
				if self.is_enum:
					if self.values is None:
						raise RuntimeError("enum must have at least 1 item")
					setattr(self.FcObj,self._name,list(self.values))
					
				if self.expression:
					self.FcObj.setExpression(prop_name, self.expression)
					self.FcObj.recompute()
				elif self.defOpValue is not None:
					return setattr(self.FcObj,self._name,self.defOpValue)
				elif self.def_value is not None:
					return setattr(self.FcObj,self._name,self.def_value)

		def getValue(self):
			fcObj = getattr(self.FcObj,self._name)
			if hasattr(fcObj,"Value"):
				return fcObj.Value
			return fcObj


	# =============================================================================
	# List of Properties
	# =============================================================================

	class Properties:
		"""
		List of Properties
		"""
		def __init__(self, **descr : PropertyDescr):
			self._post_properties : Dict[str,PostProperty] = {}
			self._op_prop_descr_list : Dict[str,PropertyDescr]= {}	#here we store the raw descr dict to create an instance for each cam operation
			self.add_properties(**descr)
			
		def add_post_property(self, name : str, obj : PostProperty):
			setattr(self,name,obj)
			self._post_properties[name] = obj

		def add_operation_property(self, prop : OperationProperty):
			setattr(self,prop._name,prop)

		def add_properties(self, **kwargs : PropertyDescr):
			for k in kwargs:
				descr = kwargs[k]
				if not descr.title:
					descr.title = k
				scope = descr.scope
				if "post" in scope:
					prop_inst = instantiate_property_gui(kwargs[k])		
					self.add_post_property(k,prop_inst)
				if "op" in scope:
					self._op_prop_descr_list[k] = descr

		def create_operation_properties(self):
			res : List[OperationProperty] = []
			descrs = self._op_prop_descr_list
			for k in descrs:
				prop_inst = OperationProperty(k,descrs[k])
				res.append(prop_inst)
			return res

		def append_properies(self, properties : Properties):
			post_properties_to_add = properties._post_properties
			for k in post_properties_to_add:
				self.add_post_property(k,post_properties_to_add[k])
			self._op_prop_descr_list.update(properties._op_prop_descr_list)

		def to_dict(self):
			data = {}
			for name, post_property in self._post_properties.items():
				data[name] = post_property.value
			return data

		def from_dict(self, _dict):
			for k in _dict:
				if not k in self._post_properties:
					continue
				self._post_properties[k].setValue(_dict[k])

		@property
		def post_propeties(self) -> Iterator[Tuple[str, PostProperty]]:
			return iter(self._post_properties.items())
				
		def __str__(self):
			res = []
			for k in self._post_properties:
				res.append(f"{k} = {self._post_properties[k]}")
			return "\n".join(res)

		def __getattr__(self, name: str) -> PropertyBase:
			raise AttributeError(name)

	"""
	this is what the user will use
	"""
	class Property(PropertyDescr):
		pass


except Exception as e:
	raise Exception(f"exception in post_properties.py: {e}")