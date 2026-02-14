# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

try:
	import PathScripts.PathUtils as PathUtils # type: ignore[import-not-found]

	from typing import List, Dict, Any

	from .post_properties import Properties, Property

	Values = Dict[str, Any]
	Visible = Dict[str, bool]

	class IJob:
		PostProcessorArgs = []
		def __iter__(self):
			return iter([])

	class IPostProcessor:
		_tooltip : str = ""
		_job : IJob = IJob()
		
		def __init__(self,job,tooltip,tooltipargs,units) -> None:
			pass

		def init_values(self,values: Values):
			pass

		def init_arguments_visible(self, arguments_visible: Visible) -> None:
			pass

		def _buildPostList(self) -> List[IJob]:
			return []

	class ToolWrapper:
		def __init__(self, _tool, _number, _label):
			self.Ftool = _tool
			self.Fnumber = _number
			self.Flabel = _label
		
		def label(self):
			return f"{self.Flabel}"

		def number(self):
			return self.Fnumber
			
		def __str__(self):
			return f"T{self.Fnumber}".ljust(7) + f"D={self.Ftool.Diameter}".ljust(12) + f"{self.Flabel}"

	class ToolList:
		def __init__(self):
			self.tools = []
			
		def append(self, tool):
			self.tools.append(tool)
			
		def __iter__(self):
			return iter(self.tools)


	class IToolController:
		class IVelocotiy:
			Value : float = 0
		Name = ""
		HorizFeed : IVelocotiy = IVelocotiy()
		VertFeed : IVelocotiy = IVelocotiy()
		SpindleSpeed : float = 0

	class CamOperation():
		def __init__(self, _fcOp):
			self.FcOp = _fcOp

			if not self.isMachiningOperation():
				return

			"""
			previously we've linked the speeds to the ones specified in the tool via expression,
			but this can lead to missing references and strange errors if the tool is deleted

			tn = self._get_toolcontroller().Name
			"""
			self.properties = Properties(
				spindleSpeed = Property(
					type = "Float",
					scope = ["post"],
					title = "SpindleSpeed",
					hint = (
						"Spindle Speed in RPM for this operation \n"
						"positive numbers: CW \n"
						"negative numbers: CCW \n"
						"0: Speed configured for the tool"
					),
					value = 0,
					#expression = f"{tn}.SpindleDir==2?0:{tn}.SpindleDir==0?{tn}.SpindleSpeed:-{tn}.SpindleSpeed"
				),
				horizFeed = Property(
					type = "Velocity",
					scope = ["op"],
					title = "HorizFeed",
					hint = "Feed for horizontal movements in mm/min",
					value = 0,
					#expression = f"{tn}.HorizFeed"
				),
				vertFeed = Property(
					type = "Velocity",
					scope = ["op"],
					title = "VertFeed",
					value = 0,
					#expression = f"{tn}.VertFeed",
					hint = "Feed for vertical movements in mm/min",
				),
				rampFeed = Property(
					type = "Velocity",
					scope = ["op"],
					title = "RampFeed",
					value = 0,
					#expression = f"horizFeed*0.8",
					hint = "Feed for movements in XZ, YZ or XYZ direction i.e. ramp entry direction in mm/min",
				),
			)
			self.install_properties(self.properties)

		def install_properties(self, properties : Properties):
			op_props = properties.create_operation_properties()
			for p in op_props:
				p.install(self.FcOp)
				self.properties.add_operation_property(p)

		def getFcOp(self):
			return self.FcOp

		def _get_property_from_obj(self, obj,_prop):
			if hasattr(obj,_prop):
				return getattr(obj,_prop)
			if not hasattr(obj,"Base"):
				raise RuntimeError("No Safe Height")
			return self._get_property_from_obj(getattr(obj,"Base",None),_prop)

		def _get_toolcontroller(self) -> IToolController:
			return self._get_property_from_obj(self.FcOp,"ToolController")

		@property 
		def safe_height(self) -> float:
			return self._get_property_from_obj(self.FcOp,"SafeHeight").Value

		@property
		def spindle_speed(self) -> float:
			sp = self.properties.spindleSpeed.value
			if sp > 0.01:
				return sp
			return self._get_toolcontroller().SpindleSpeed
		
		@property
		def horiz_feed(self) -> float:
			feed = self.properties.horizFeed.value
			if feed > 0.01:
				return feed
			return self._get_toolcontroller().HorizFeed.Value
			
		@property
		def vert_feed(self) -> float:
			feed = self.properties.vertFeed.value
			if feed > 0.01:
				return feed
			return self._get_toolcontroller().VertFeed.Value
			
		@property
		def rapid_feed(self) -> float:
			return self.properties.rapidFeed.value
			
		@property
		def ramp_feed(self) -> float:
			feed = self.properties.rampFeed.value
			if feed > 0.01:
				return feed
			return self.horiz_feed
			
		@property
		def transition_feed(self) -> float:
			return self.properties.transitionFeed.value
			
		def getCoolant(self):
			obj = self.FcOp
			coolantMode = "None"
			if self.properties.coolantOverride.value:
				return self.properties.coolant.value
			if hasattr(obj, "CoolantMode") or hasattr(obj, "Base") and hasattr(obj.Base, "CoolantMode"):
				if hasattr(obj, "CoolantMode"):
					coolantMode = obj.CoolantMode
				else:
					coolantMode = obj.Base.CoolantMode
			return coolantMode

		def isMachiningOperation(self):
			return self.FcOp.Path.Length > 0

		def isToolChangeOperation(self) -> bool:
			"""
			Checks whether the operation is a tool change. If this method returns True, calling 
			``getToolWrapper()`` is safe and valid.

			Returns:
					bool: True if FcOp has a Tool attribute, otherwise False.
			"""
			return hasattr(self.FcOp,"Tool")

		def getToolWrapper(self):
			return ToolWrapper(self.FcOp.Tool,self.FcOp.ToolNumber,self.FcOp.Label)

		def getLabel(self):
			return self.FcOp.Label

		def getCommands(self):
			return iter(PathUtils.getPathWithPlacement(self.FcOp).Commands)

		def label(self):
			return self.FcOp.Label

		def __str__(self):
			return f"{self.FcOp.Label}"

		"""
		def getOpLabel(self, obj):
			if hasattr(obj,"Base"):
				return getattr(obj.Base, "Label", obj.Label)
			return obj.Label
		"""


	class CamOperations:
		def __init__(self):
			self.Foperations : List[CamOperation] = []

		def append(self,_op):
			self.Foperations.append(_op)

		def getTools(self):
			tools = ToolList()
			for c in self.Foperations:
				if c.isToolChangeOperation():
					tools.append(c.getToolWrapper())
			return tools
		
		def getMachiningOperations(self) -> List[CamOperation]:
			mo : List[CamOperation] = []
			for o in self.Foperations:
				if o.isMachiningOperation():
					mo.append(o)
			return mo

		def __iter__(self):
			return iter(self.Foperations)

except Exception as e:
	raise Exception(f"Exception in wrappers.py {e}")
