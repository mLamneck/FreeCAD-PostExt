# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

try:

	# import FreeCAD related stuff 
	import FreeCAD # type: ignore[import-not-found]
	import Path	# type: ignore[import-not-found]
	import Path.Base.Util as PathUtil # type: ignore[import-not-found]
	import Path.Post.Utils as PostUtils # type: ignore[import-not-found]
	import PathScripts.PathUtils as PathUtils # type: ignore[import-not-found]
	from Path.Post.Processor import PostProcessor # type: ignore[import-not-found]

	# typing
	from typing import Optional, List, Unpack, Type, Dict, cast, final
	from enum import Enum

	# python commons
	import os
	import math

	# helpers from this module
	from . import utils
	from .gui import SettingsDialog
	from .post_properties import Property, Properties, PropertyDescr
	from .path_geometry import calc_circlular_sweep, calc_radius, linearize_circular, Coordinate
	from .output_formatting import OutputParams, OutputVariable, Outstream, Warning, Warnings, Resettable, CoolantManager, CoolantManager, Coolant
	from .wrappers import ToolList, CamOperation, CamOperations, ArrayCamOperation, IPostProcessor, Values, Visible
	from .debug import objToList

	#FreeCAD switched to Qt6 in later releases
	try:
		from PySide6 import QtWidgets # type: ignore[import-not-found]
	except ImportError:
		from PySide2 import QtWidgets # type: ignore[import-not-found]
  

	# =============================================================================
	# Helpers and Defines
	# =============================================================================

	def toMmPerMin(val : float):
		return val * 60.0

	def toMmPerSec(mmPerMin : float):
		return mmPerMin/60.0

	class Plane(Enum):
		XY = "G17"
		XZ = "G18"
		YZ = "G19"

	class MovementType(Enum):
		UNKNOWN = -1
		LINEAR = 0
		CIRCLE = 1
		HELIX = 2
		SPIRAL = 3

	class MotionMode(Enum):
		ABS = "G90"
		REL = "G91"

	class DrillRectractMode(Enum):
		Z = "G98"    #retract to previous Z after drilling
		R = "G99"    #retract only to R (parameter of G81,...) after drilling

	class PathCmd:
		"""
		Wrapper around FreeCAD CAM path command objects.

		CAM may emit equivalent movement commands with different names
		(e.g. G0 and G00). This wrapper normalizes them to avoid special
		handling in multiple places.
		"""
		def __init__(self,_fc_cmd) -> None:
			self._fc_cmd = _fc_cmd
			self._name = _fc_cmd.Name
			if self._name in ["G00","G01","G02","G03"]:
				self._name = self._name[0] + self._name[2]

		@property
		def Name(self) -> str:
			return self._name
		
		@property
		def Parameters(self) -> dict:
			return self._fc_cmd.Parameters


	# =============================================================================
	# Postprocessor Base Functionality
	# =============================================================================

	class BasePostExt(cast(Type[IPostProcessor], PostProcessor)):

		def __init__(self, job, tooltip, tooltipargs, units, 
				coolants : List[str],
				file_ending : str ="ncp",
				cmt_fmt : str ="({:s})",
				machine_accel : float = 2000,
				)-> None:
			super().__init__(
				job=job,
				tooltip=tooltip,
				tooltipargs=tooltipargs,
				units=units,
			)
			
			self.JOB = job
			self.POST_NAME = self.__class__.__name__
			self.FILE_ENDING = file_ending
			self.CMT_FMT = cmt_fmt
			self.MACHINE_ACCEL = machine_accel

			self._available_coolants = coolants
			self._objects_list = None
			self._filename : str = ""
			self._tools : ToolList | None = None
			self._curr_operation : CamOperation | None = None
			self._curr_cmd : PathCmd | None
			self._out : Outstream = Outstream(cmt_format=self.CMT_FMT)
			self._final_code : str = ""
			self._warnings : Warnings = Warnings()

			self._resetable_objects : List[Resettable] = []

			self._settings_dialog: Optional[SettingsDialog] = None

			# states over multiple cmds
			self._spindle_is_on : bool = False
			self._curr_plane : Plane = Plane.XY
			self._curr_position : Coordinate = Coordinate()
			self._motion_mode : MotionMode = MotionMode.ABS             #G90->absolute G91 relative (we don't support relative movements at the moment)
			self._drill_retract_mode : DrillRectractMode = DrillRectractMode.Z
			
			self._curr_movement_type : MovementType = MovementType.UNKNOWN

			self._cycle_time : float = 0
			self._suppress_invoke_onLinear : bool = False

			# common properties available for all posts
			self._properties  = Properties(
				coolantOverride = Property(
					title = "Override Coolant",
					scope = ["op"],
					hint = (
						"Override coolant for this operation"
					),
					value = False
				),
				coolant = Property(
					title = "Coolant",
					scope = ["op"],
					values = self._available_coolants,
				),
				safeInitialPositionings = Property(
					group = "Path Modification",
					title = "Safe initial positioning (XY first, then Z)",
					hint = (
						"Moves the tool to the start XY position before lowering Z at the beginning \n"
						"of the job. This avoids diagonal X,Y/Z or moves and makes the initial motion \n"
						"more predictable. Make sure your machine is on a safe height on start or after \n"
						"a Toolchange operation"
					),
					value = True
				),
				linearizationTol = Property(
					#group = "Path Modification",
					title = "Tolerance for linearizing arcs, helices and spirals",
					hint = (
						"Defines the maximum allowed deviation when converting arcs, helices and \n"
						"spirals into linear segments. Smaller values create smoother toolpaths \n"
						"with more G-code, while larger values reduce code size but may lower \n"
						"geometric accuracy."
					),
					decimals = 3,
					step = 0.001,
					value = 0.019
				),
				expandDrillingCycles = Property(
					group = "Path Modification",
					title = "Expand Drilling Cycles",
					hint = (
						"Expand drilling cylces into linear movements"
					),
					value = True
				),
				drillingG73retract = Property(
					group = "Path Modification",
					title = "G73 Retract",
					hint = (
						"Relative retract distance for the G73 drilling cycle. \n"
						"Specifies how far the tool retracts from the current hole depth \n"
						"between peck steps to break chips. \n"
						"This value is used internally by the postprocessor and is not \n"
						"output as an explicit NC parameter."
					),
					value = 1.0
				),
				rapidFeed = Property(
					type = "Velocity",
					group = "Path Modification",
					title = "RapidFeed",
					widget_scale = 60,
					min = 0,
					max = 10000,
					decimals = 0,
					scope = ["post","op"],
					hint = (
						"Feed rate in mm/min for G0 (rapid) moves. Primarily used for machining time\n"
						"calculation; if supported by the controller, it may also be emitted in the\n"
						"postprocessed code. The value can be defined globally and overridden per\n"
						"operation. If set to 0 in an operation, the global property is used."
					),
					value = toMmPerSec(5000),
					op_value = toMmPerSec(0),	#by default use global rapidFeed for jobs
				),
				transitionFeed = Property(
					type = "Velocity",
					group = "Path Modification",
					scope = ["post","op"],
					title = "TransitionFeed",
					widget_scale = 60,
					decimals=0,
					min=0,
					max=10000,
					value = toMmPerSec(3000),
					op_value=0,
					hint = (
						"Feed rate used to replace certain G0 rapid moves with G1 transitions\n"
						"to avoid jerky motion caused by chained rapids in FreeCAD Adaptive jobs.\n"
						"Only applied below safe Z; true rapids are kept when moving to or above safe Z.\n"
						"If set to 0 in an operation, the global property is used."
					),
				),
			)
			self._properties.append_properies(self._out.properties)


		# -----------------------------------------------------------------------------
		# Adatper to FreeCAD's Base Postprocessor
		# -----------------------------------------------------------------------------

		def init_values(self, values: Values) -> None:
			"""Initialize values that are used throughout the postprocessor."""
			super().init_values(values)
			values["MACHINE_NAME"] = "UNKNOWN"

		def init_arguments_visible(self, arguments_visible: Visible) -> None:
			super().init_arguments_visible(arguments_visible)

		def export(self):
			"""Dynamically reload the module for the export to ensure up-to-date usage."""
			postables = self._buildPostList()
			Path.Log.debug(f"postables count: {len(postables)}")

			# if split output is selected we get multiple sections that have to be
			# individually processed. Here we iterate over all postables first to attach 
			# all properties to the jobs
			nPostRuns = 0
			for idx, section in enumerate(postables):
				nPostRuns += 1
				partname, sublist = section
				operations = self._build_operations_wrappers_from_objects_list(sublist)
				for op in operations:
					if op.isMachiningOperation():
						op.install_properties(self._properties)

			if not self._open_settings_dialog(self._properties,operations):
				return [("",None)]

			# post processing...
			for idx, section in enumerate(postables):
				partname, sublist = section
				filename = self.settings_dialog.filename
				if nPostRuns > 1:
					name, ext = os.path.splitext(filename)
					filename = f"{name}_{idx}{ext}"
				self.initRun(sublist,filename,self._job.PostProcessorArgs)
				self.run()

			return [("",None)]

		@property
		def tooltip(self):
			return self._tooltip


		# -----------------------------------------------------------------------------
		# State across post run
		# -----------------------------------------------------------------------------

		def _reset_objects(self):
			for o in self._resetable_objects:
				o.reset()

		def initRun(self, _objectslist, _filename, _argstring):
			self._objects_list = _objectslist
			self._filename : str = _filename
			self._tools = None
			self._curr_operation  = None
			self._curr_cmd = None
			self._out : Outstream = Outstream( cmt_format = getattr(self,"CMT_FMT","({:s})") )
			self._final_code : str = ""
			self._warnings : Warnings = Warnings()

			# states over multiple cmds
			self._coolantHandled : bool = False
			self._spindle_is_on : bool = False
			self._curr_plane : Plane = Plane.XY
			self._curr_position : Coordinate = Coordinate()
			self._motion_mode : MotionMode = MotionMode.ABS             #G90->absolute G91 relative (we don't support relative movements at the moment)
			self._drill_retract_mode : DrillRectractMode = DrillRectractMode.Z
			
			self._curr_movement_type : MovementType = MovementType.UNKNOWN

			self._cycle_time : float = 0
			self._suppress_invoke_onLinear : bool = False

			self._reset_objects()

		@property
		@final
		def tools(self) -> ToolList:
			assert self._tools is not None, "_tools not initialized"
			return self._tools
		
		@property
		@final
		def curr_operation(self) -> CamOperation:
			assert self._curr_operation is not None, "_curr_operation not initialized"
			return self._curr_operation
		
		@property
		@final
		def curr_cmd(self) -> PathCmd:
			assert self._curr_cmd is not None, "_curr_cmd not initialized"
			return self._curr_cmd
		
		@property
		@final
		def curr_plane(self):
			return self._curr_plane
		
		@property
		@final
		def curr_position(self):
			return self._curr_position
		
		@property
		@final
		def objects_list(self):
			assert self._objects_list is not None, "_objects_list not initialized"
			return self._objects_list

		# -----------------------------------------------------------------------------
		# State across all runs
		# -----------------------------------------------------------------------------

		@property
		@final
		def filename(self):
			return self._filename
		
		@property
		@final
		def out(self):
			return self._out
		
		@property
		@final
		def warnings(self):
			return self._warnings
		
		@property
		@final
		def settings_dialog(self):
			assert self._settings_dialog is not None, "Settings Dialog not initialized"
			return self._settings_dialog
		

		# -----------------------------------------------------------------------------
		# internal methods
		# -----------------------------------------------------------------------------

		def _open_settings_dialog(self, properties : Properties, cam_operations : CamOperations):
			self._settings_dialog = SettingsDialog(properties,cam_operations,self)
			if self._settings_dialog.exec_() == QtWidgets.QDialog.Accepted:
				return True
			return None

		def _get_coolant(self):
			if self._curr_operation is None:
				raise RuntimeError("No current operation set")
			return self._curr_operation.getCoolant()
				
		def is_close(self,_a, _b):
			if _a is None or _b is None:
				return False
			return math.isclose(_a, _b, rel_tol=1e-6, abs_tol=1e-9)

		def error(self,_err):
			if self._curr_operation:
				raise Exception(f"{self._curr_operation.getLabel()}: {_err}")
			raise Exception(_err)

		def _build_operations_wrapper(self, wrapperList : CamOperations, obj):
			if hasattr(obj, "Group"):
				for p in obj.Group:
					self._build_operations_wrapper(wrapperList,p)
				return

			# groups might contain non-path things like stock.
			if not hasattr(obj, "Path"):
				self.error(f"The object {obj.Name} is not a path. Please select only path and Compounds.")
				return

			# Skip inactive operations
			if PathUtil.opProperty(obj, "Active") is False:
				return

			camOp = CamOperation(obj)
			wrapperList.append(camOp)

		def _build_operations_wrappers_from_objects_list(self, objects_list) -> CamOperations:
			#iterate over "operations"
			#an operation can be a Fixture, a Tool change or a path
			wrappers = CamOperations()

			for obj in objects_list:
				self._build_operations_wrapper(wrappers,obj)

			#flatten array operations and create a final list with operations
			finalWrappers = CamOperations()
			for op in wrappers:
				if not op.isArrayOperation():
					finalWrappers.append(op)
					continue

				array_jobs_list = getattr(op.FcOp,"Base",None)
				assert isinstance(array_jobs_list,list), "Base of array is not a list"

				cam_ops : list[CamOperation] = []
				for j in array_jobs_list:
					base_op = wrappers.find_by_fc_ref(j)
					assert base_op, f"operation \"{getattr(j,'Label','no label')}\" from arrays \"{op.label()}\" base selection not found. Check array selection and restrict to outer dressup!"
					cam_ops.append(base_op)

				array_inst_cnt = 0
				op_index = 0
				curr_base_op = cam_ops[0]
				cmd_cnt = 0
				curr_op = ArrayCamOperation(curr_base_op.FcOp,op,array_inst_cnt)
				for c in op.getCommands():
					cmd_cnt += 1

					#one operation has been completed
					if cmd_cnt >= curr_base_op.cmd_cnt():
						finalWrappers.append(curr_op)
						cmd_cnt = 0
						op_index += 1

						# all operations within the array has been completed
						if op_index >= len(cam_ops):
							op_index = 0
							array_inst_cnt += 1

						curr_base_op = cam_ops[op_index]
						curr_op = ArrayCamOperation(curr_base_op.FcOp,op,array_inst_cnt)

					curr_op.addCmd(c)
				assert cmd_cnt==0 and op_index==0, "number of cmds in array doesn't match. Check array selection!"
			return finalWrappers

		def _build_operations_wrappers(self) -> CamOperations:
			return self._build_operations_wrappers_from_objects_list(self.objects_list)

		def get_reorder_pos_cmt(self,cmd_stack : List[PathCmd]):
			l = ""
			for pc in cmd_stack:
				p = pc.Parameters
				x = f" X{p['X']:.2f}" if p.get("X",None) is not None else ""
				y = f" Y{p['Y']:.2f}" if p.get("Y",None) is not None else ""
				z = f" Z{p['Z']:.2f}" if p.get("Z",None) is not None else ""
				l += f'   {pc.Name}{x}{y}{z}'
			return l

		def _check_enable_coolant(self):
			if not self._coolantHandled:
				self._coolantHandled = True
				self.onCoolant(self._get_coolant())

		def _get_feed(self,x,y,z):
			moveInX = not self.is_close(self._curr_position.x,x)
			moveInY = not self.is_close(self._curr_position.y,y)
			moveInZ = not self.is_close(self._curr_position.z,z)
			if not moveInZ:
				feed = self.curr_operation.horiz_feed
			elif moveInX or moveInY:
				feed = self.curr_operation.ramp_feed
			else:
				feed = self.curr_operation.vert_feed
			if self.is_close(feed,0):
				raise Exception(f"feed = 0 not allowed in operation {self.curr_operation.getLabel()}")
			return feed

		def _get_rapid_feed(self):
			opFeed = self.curr_operation.rapid_feed
			if opFeed > 0:
				return opFeed
			return self._properties.rapidFeed.value

		def _get_transition_feed(self):
			if  self.curr_operation.transition_feed > 0:
				return self.curr_operation.transition_feed
			return self._properties.transitionFeed.value

		def _calc_dist(self,_x,_y,_z):
			x,y,z = self._curr_position.x, self._curr_position.y, self._curr_position.z
			dx = (x-_x) if x is not None and _x is not None else 0
			dy = (y-_y) if y is not None and _y is not None else 0
			dz = (z-_z) if z is not None and _z is not None else 0
			dist = math.sqrt(dx*dx+dy*dy+dz*dz)
			return dist

		def _calc_required_dist_for_feed(self,_feed):
			return _feed*_feed / self.MACHINE_ACCEL

		def _calc_time_for_linear_movement(self,_x,_y,_z,_feed):
			v =_feed
			a = self.MACHINE_ACCEL

			s_min = v*v / a
			dist = self._calc_dist(_x,_y,_z)
			if dist >= s_min:
				t = 2*(v/a) + (dist - s_min)/v
			else:
				t = 2*math.sqrt(dist / a)
			self._cycle_time += t

		def _get_movement_type(self, s0,s1,s2, e0,e1,e2 ,c0,c1):
			radius_start = calc_radius(s0,s1,c0,c1)
			radius_end = calc_radius(e0,e1,c0,c1)
			if not self.is_close(radius_start,radius_end):
				return MovementType.SPIRAL
			
			if not self.is_close(s2,e2):
				return MovementType.HELIX

			return MovementType.CIRCLE

		def _linearize(self):
			c = self.curr_cmd
			
			cmdName = c.Name
			if not (cmdName == "G2" or cmdName == "G3"):
				self.error(f"invalid cmd in linearize: '{cmdName}', allowed cmds: G2, G3")

			# make sure we know the current position
			x,y,z = self._curr_position.x, self._curr_position.y, self._curr_position.z
			assert (x is not None and y is not None and z is not None)

			clockwise = cmdName=="G2"
			epsilon = self._properties.linearizationTol.value
			
			if self._curr_plane is Plane.XY:
				chords = linearize_circular(
					c.Parameters.get("I",0), c.Parameters.get("J",0),
					x, y, z,
					c.Parameters.get("X",x),c.Parameters.get("Y",y),c.Parameters.get("Z",z),
					clockwise,
					epsilon
				)
				for p in chords[1:]:
					self.invokeOnLinear(p[0],p[1],p[2])
			
			elif self._curr_plane is Plane.XZ:
				chords = linearize_circular(
					c.Parameters.get("I",0), c.Parameters.get("K",0),
					x, z, y,
					c.Parameters.get("X",x), c.Parameters.get("Z",z), c.Parameters.get("Y",y),
					clockwise,
					epsilon
				)
				for p in chords[1:]:
					self.invokeOnLinear(p[0],p[2],p[1])

			elif self._curr_plane is Plane.YZ:
				chords = linearize_circular(
					c.Parameters.get("J",0), c.Parameters.get("K",0),
					y, z, x, 
					c.Parameters.get("Y",y),c.Parameters.get("Z",z), c.Parameters.get("X",x),
					clockwise,
					epsilon
				)
				for p in chords[1:]:
					self.invokeOnLinear(p[1],p[2],p[0])

			else:
				self.error("invalid plane")


		def expand_drilling_cycle(self,cmd : str, params):
			"""
			expand a drilling cycle into linear movements
			supported:
				drilling cycles:
					G81: no option set
					G82: option: dwell
					G83: option: peck
					G85: option: Feed Retract
					G73: option: peck + chip break
				retract mode:
					G98: no option set            -> rectract to previous Z
					G99: option: keep tool down   -> rectract to R parameter
			"""
			self.writeWarning("drilling cycles not tested")
			x = params.get("X",None)
			y = params.get("Y",None)
			drillZ = params.get("Z")
			startZ = params["R"]
			assert self._curr_position.z is not None

			# G98 -> retract to curr Z, but only if Z > startZ (R)
			# G99 -> retract to R Parameter 
			retractZ = startZ
			if self._drill_retract_mode is DrillRectractMode.Z and startZ < self._curr_position.z:
				retractZ = self._curr_position.z
			
			if startZ < drillZ:
				raise self.error("Drill cycle error: R < Z")

			# retract first if Z is below retract plane
			if self._curr_position.z < retractZ:
				self.invokeOnRapid(None, None, retractZ)

			# position above hole
			self.invokeOnRapid(x, y, None)

			# go down to startZ
			if self._curr_position.z > startZ:
				self.invokeOnLinear(None, None, startZ)

			# drilling cycles
			# G81: regular drilling: G81 F2.5 R14 X10 Y10 Z0  -> start at Z=14 and go down to 0, retract to R or previous Z depending current mode (G98,G99)
			# G82: same as G81 but with an addional parameter P -> pause n seconds at the bottom
			if cmd in ("G81", "G82", "G85"):  #G84
				self.invokeOnLinear(None, None, drillZ)
				if cmd == "G82":
					dwell = params.get("P", 0)
					if dwell > 0:
						self.invokeOnDwell(dwell)
				if cmd == "G85":
					self.invokeOnLinear(None, None, retractZ)
				else:
					self.invokeOnRapid(None, None, retractZ)

			# G83: deep drilling: G83 F2.5 Q3 R14 X10 Y10 Z0 -> same as G81 but 
			# G73                 G73 F2.5 Q3 R14 X10 Y10 Z0 -> same as G83 but no full retract, but an ?abitrary? relative rectrat
			#                                                   that might be adjustable with PP properties?
			elif cmd in ("G83","G73"):
				step = params["Q"]
				current_depth = retractZ
				G73_retract = 1.0       # toDo: make it a property

				while current_depth > drillZ:
					current_depth = max(current_depth - step, drillZ)
					self.invokeOnLinear(None, None, current_depth)
					if cmd == "G83":
						self.invokeOnRapid(None, None, retractZ)
					elif cmd == "G73":
						self.invokeOnRapid(None, None, current_depth+G73_retract)

			# G84: thread milling -> same parameters like G81 but F might be the thread pitch: to be checked 
			elif cmd in ("G84"):
				self.error("G84 (thread milling) not implemented")


		# -----------------------------------------------------------------------------
		# public methods
		# -----------------------------------------------------------------------------

		def writeBlock(self, *args):
			self._out.writeBlock(*args)
			
		def writeBlocks(self, _list):
			self._out.writeBlocks(_list)

		def writeSeperation(self):
			self._out.writeSeparation()

		def writeComment(self,*args):
			self._out.writeComment(*args)

		def writeWarning(self, _warning : str):
			self._warnings.add(Warning(job=self.curr_operation,text=_warning))
		
		def getAbsCenter(self,i,j,k) -> Coordinate:
			rel_center = Coordinate(i,j,k)
			return rel_center + self.curr_position

		def createProperties(self,**kwargs : PropertyDescr):
			s = Properties(**kwargs)
			self._properties.append_properies(s)
			return s
		
		def createCoolantManager(self, *coolants : Coolant):
			c = CoolantManager(*coolants)
			self._resetable_objects.append(c)
			return c
		
		def createOutputVariable(self,**kwargs: Unpack[OutputParams]):
			o = OutputVariable(**kwargs)
			self._resetable_objects.append(o)
			return o
		
		def getCircularSweep(self):
			c = self.curr_cmd
			
			cmdName = c.Name
			if not (cmdName == "G2" or cmdName == "G3"):
				self.error(f"invalid cmd in getCircularSweep: '{cmdName}', allowed cmds: G2, G3")

			if self._curr_plane is Plane.XY:
				assert(self._curr_position.x is not None and self._curr_position.y is not None)
				return calc_circlular_sweep(c.Parameters.get("I",0), c.Parameters.get("J",0), self._curr_position.x, self._curr_position.y, c.Parameters.get("X",self._curr_position.x), c.Parameters.get("Y",self._curr_position.y), cmdName=="G2")
			elif self._curr_plane is Plane.XZ:
				assert(self._curr_position.x is not None and self._curr_position.z is not None)
				return calc_circlular_sweep(c.Parameters.get("I",0), c.Parameters.get("K",0), self._curr_position.x, self._curr_position.z, c.Parameters.get("X",self._curr_position.x), c.Parameters.get("Z",self._curr_position.z), cmdName=="G2")
			elif self._curr_plane is Plane.YZ:
				assert(self._curr_position.y is not None and self._curr_position.z is not None)
				return calc_circlular_sweep(c.Parameters.get("J",0), c.Parameters.get("K",0), self._curr_position.y, self._curr_position.z, c.Parameters.get("Y",self._curr_position.y), c.Parameters.get("Z",self._curr_position.z), cmdName=="G2")
			self.error("invalid plane")

		def isHelix(self):
			return self._curr_movement_type == MovementType.HELIX
		
		def isSpiral(self):
			return self._curr_movement_type == MovementType.SPIRAL

		def linearize(self):
			self.writeWarning("linearize not tested... ")
			self._linearize()

		def getCycleTime(self):
			return self._cycle_time

		def getCycleTimeStr(self):
			t = int(round(self._cycle_time))

			hours = t // 3600
			minutes = (t % 3600) // 60
			seconds = t % 60

			return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

		# -----------------------------------------------------------------------------
		# only debugging... toDo: move to debug.py
		# -----------------------------------------------------------------------------

		def logParameters(self):
			c = self.curr_cmd
			for p in c.Parameters:
				self.writeBlock(f"{p} = {c.Parameters[p]}")

		def createDebugOutput(self):

			def createDebugOutputForObj(obj,label="",indent=""):
				if hasattr(obj, "Group"):
					self.writeBlock(indent,"enter group ---------------------------------------")
					for p in obj.Group:
						createDebugOutputForObj(p)
					return

				self.writeBlock(indent,"-> -------------" + label if label else obj.Label)
				self.writeBlocks(objToList(obj,indent+"  "))
				if hasattr(obj, "Base"):
					base = getattr(obj,"Base")
					if isinstance(base,list):
						self.writeBlock("isLIst")
						for o in base:
							createDebugOutputForObj(o,f"Base({obj.Label}) = {getattr(o,'Label','no label')}",f"{indent}  ")	
					else:
						self.writeBlock(indent,"  ----------------------- Base",getattr(base,"Label","no label"))
						#self.writeBlocks(objToList(obj.Base))
						createDebugOutputForObj(base,f"Base({obj.Label}) = {getattr(base,'Label','no label')}",f"{indent}  ")
					self.writeBlock(indent,"----------------------- ")
				else:
					self.writeBlock(indent,"  no base")

				if hasattr(obj, "ToolController"):
					self.writeBlock(indent,"----------------------- ToolController")
					self.writeBlocks(objToList(obj.ToolController,indent))
					self.writeBlock(indent,"----------------------- ")
				else:
					self.writeBlock(indent,"  no ToolController")

				if label:
					return
				if 1 == 1:
					for c in PathUtils.getPathWithPlacement(obj).Commands:
						#self.writeBlock("-> cmd -------------")
						if c.Name.startswith("("):  # command is a comment
							self.writeBlock(indent,f"  COMMENT '{c.Name}'------------")
						else:
							self.writeBlock(indent,f"  CMD '{c.Name}'------------")
						#self.writeBlock(objToList(c))

				self.writeBlock(indent,"<- -------------" + obj.Label)

			for obj in self.objects_list:
				self.FdummyObj = obj
				createDebugOutputForObj(obj)
			if FreeCAD.GuiUp:
				self._final_code = self._out.toString()
				dia = PostUtils.GCodeEditorDialog()
				dia.editor.setText(self._final_code)
				result = dia.exec_()
				if result:
						self._final_code = dia.editor.toPlainText()


		# -----------------------------------------------------------------------------
		# process one postable
		# -----------------------------------------------------------------------------

		def run(self):
			try:
				#return self.createDebugOutput()
				
				operations = self._build_operations_wrappers()
				for op in operations.getMachiningOperations():
					op.install_properties(self._properties)

				self._tools = operations.getTools()

				self.beforeExport()
				
				self._cycle_time = 0
				for op in operations:
					self._curr_operation = op

					if op.isMachiningOperation():
						self.beforeOperation(op)

						if op.spindle_speed <= 0:
							self.writeWarning("spindleSpeed=0")
						self.invokeOnSpindleSpeed()

					"""
					now iterate over all cmds within an operation and translate
					"""
					cmdStack = []
					startCoord = Coordinate()
					self._coolantHandled = False
					for c in op.getCommands():
						if c.Name.startswith("("):
							continue

						self._curr_movement_type = MovementType.UNKNOWN
						c = PathCmd(c)
						self._curr_cmd = c
						cmd = c.Name
						if cmd in ["G0","G1","G2","G3"]:
							self._curr_movement_type = MovementType.LINEAR
							x = c.Parameters.get("X",self._curr_position.x)
							y = c.Parameters.get("Y",self._curr_position.y)
							z = c.Parameters.get("Z",self._curr_position.z)
					
							"""
							"Moves the tool to the start XY position before lowering Z at the beginning "
							"of the job. This avoids diagonal X,Y/Z or moves and makes the initial motion "
							"more predictable. Make sure your machine is on a safe height on start or after "
							"a Toolchange operation"
							"""
							if not self._curr_position.is_valid() and self._properties.safeInitialPositionings.value:
								if cmd in ["G2","G3"]:
									self.error("G2,G3 not allowed if XY is not positioned")
								cmdStack.append(c)
								startCoord.update(c.Parameters.get("X",None),c.Parameters.get("Y",None),0)
								if startCoord.is_valid():
									self.writeWarning("Reorder cmds for initial positioning")
									self._out.writeComment("-> Reorder cmds: " + self.get_reorder_pos_cmt(cmdStack))
									self.invokeOnRapid(startCoord.x,startCoord.y,None)
									for pc in cmdStack:
										self._curr_cmd = pc
										if pc.Name in ["G0"]:
											self.invokeOnRapid(None,None,pc.Parameters.get("Z",None))
										else:
											self._check_enable_coolant()
											self.invokeOnLinear(None,None,pc.Parameters.get("Z",None))
									self._out.writeComment("<- Cmds reordered")
									cmdStack = []
								continue

							if cmd in ["G0"]:
								self.invokeOnRapid(x,y,z)
							elif cmd in ["G1"]:
								self.invokeOnLinear(x,y,z)
							elif cmd in ["G2","G3"]:
								self._check_enable_coolant()
								clockwise = cmd=="G2"
								I = c.Parameters.get("I",0)
								J = c.Parameters.get("J",0)
								K = c.Parameters.get("K",0)
								self.invokeOnCircular(clockwise,
									I,
									J,
									K,
									x,
									y,
									z,
								)
							self._curr_position.update(x,y,z)
						elif cmd == "M3":
							pass
						elif cmd == "M6":
							self.invokeOnChangeTool(c.Parameters["T"])
							self._curr_position.reset()
						elif cmd in [Plane.XY.value,Plane.XZ.value,Plane.YZ.value]:
							self._curr_plane = Plane(cmd) 
							self.onChangePlane(self._curr_plane)
						elif cmd == "G54":
							pass
						# change to absolute positioning self.motionMode is not used so far, so this has no effect
						elif cmd in [MotionMode.ABS.value]:
							self._motion_mode = MotionMode(cmd)
						elif cmd in [MotionMode.REL.value]:
							self._motion_mode = MotionMode(cmd)
							self.error("relative positioning not supported at the moment")
						elif cmd in [DrillRectractMode.Z.value,DrillRectractMode.R.value]:  #G98,G99
							self._drill_retract_mode = DrillRectractMode(cmd)
						elif cmd in ["G81","G82","G83","G84","G85","G73"]:
							if self._properties.expandDrillingCycles.value:
								self.expand_drilling_cycle(cmd,c.Parameters)
							else:
								self._check_enable_coolant()
								self.onDrillingCycle(cmd,c.Parameters)
						elif cmd in ["G80"]:
							pass
						else:
							self.error(f'exportOp: cmd {cmd} not processed')
							#self.writeBlock(f'exportOp: cmd {cmd} not processed')

					if op.isMachiningOperation():
						self.afterOperation(op)

				#self.onSpindelOff()
				self.afterExport()
				self._final_code = self._out.toString()

			except Exception as e:
				import traceback
				self._final_code = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n"
				if self.curr_operation:
					self._final_code += f"Exception in {self.curr_operation.label()}\n\n"
				self._final_code += f"{e}\n\n"
				self._final_code += traceback.format_exc()
				self._final_code += f"\nXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
				self._final_code += f"\n\n\n"
				self._final_code += f"\n{self._out.toString()}"

			if self.settings_dialog.open_nc_in_editor:
				with open(self.filename, "w") as text_file:
					text_file.write(self._final_code)
				utils.open_with_default_app(self.filename)
			elif FreeCAD.GuiUp:
					dia = PostUtils.GCodeEditorDialog()
					dia.editor.setText(self._final_code)
					result = dia.exec_()
					if result:
						self._final_code = dia.editor.toPlainText()
						with open(self.filename, "w") as text_file:
							text_file.write(self._final_code)


		#--------------------------------------------------
		# invoke Postprocessor's entry functions
		#--------------------------------------------------

		def invokeSpindleOff(self):
			if self._spindle_is_on:
				self.onSpindelOff()
				self._spindle_is_on = False

		def invokeOnSpindleSpeed(self):
			op = self.curr_operation
			rpm = op.spindle_speed
			absRpm = abs(rpm)
			if absRpm > 0.01:
				self._spindle_is_on = True
				self.onSpindelSpeed(absRpm,rpm>0.01)
			else:
				self.invokeSpindleOff()

		def invokeOnCircular(self,clockwise, i,j,k, x,y,z):
			if self.is_close(self._curr_position.z,z):
				feed = self.curr_operation.horiz_feed
			else:
				feed = self.curr_operation.ramp_feed
			if self.is_close(feed,0):
				raise Exception(f"feed = 0 not allowed in operation {self.curr_operation.getLabel()}")

			if self._curr_plane is Plane.XY:
				self._curr_movement_type = self._get_movement_type(self._curr_position.x,self._curr_position.y,self._curr_position.z, x,y,z, i,j)
			elif self._curr_plane is Plane.XZ:
				self._curr_movement_type = self._get_movement_type(self._curr_position.x,self._curr_position.z,self._curr_position.y, x,z,y, i,k)
			elif self._curr_plane is Plane.YZ:
				self._curr_movement_type = self._get_movement_type(self._curr_position.y,self._curr_position.z,self._curr_position.x, y,z,x, j,k)

			temp = self.getCycleTime()
			self.onCircular(clockwise, i,j,k, x,y,z, feed)
			if temp == self.getCycleTime():
				self._suppress_invoke_onLinear = True
				self._linearize()
				self._suppress_invoke_onLinear = False
			
		def invokeOnLinear(self,x,y,z,feed=None):
			self._check_enable_coolant()
			if feed is None:
				feed = self._get_feed(x,y,z)
			self._calc_time_for_linear_movement(x,y,z,feed)
			if not self._suppress_invoke_onLinear:
				self.onLinear(x,y,z,feed)
			self._curr_position.update(x,y,z)

		def invokeOnRapid(self,x,y,z):
			# FreeCAD CAM (especially Adaptive jobs) may generate chains of G0 moves
			# that are semantically transitions rather than true rapids.
			#
			# On many controllers, G0 moves are defined to stop at the end of each
			# block, which can lead to visible jerking and unnecessary deceleration
			# when such G0 chains are executed back-to-back.
			#
			# If enabled via property (transition_feed > 0), this post-processor
			# selectively replaces certain G0 moves with G1 moves using a dedicated
			# transition feed. This preserves continuous motion while avoiding the
			# side effects of rapid-mode stopping.
			#
			# True rapids are still emitted when moving to safe Z, above safe Z,
			# or when already safely above it. The replacement only applies to
			# transition-like moves below safe Z where smooth motion matters.
			if self._get_transition_feed() > 0:
				curr_z = self.curr_position.z
				z_is_known = curr_z is not None
				below_safe = (curr_z < self.curr_operation.safe_height - 0.001) if z_is_known else False
				if below_safe:
					move_in_x = not self.is_close(x,self._curr_position.x)
					move_in_y = not self.is_close(y,self._curr_position.y)
					go_above_safe_or_above = z > self.curr_operation.safe_height - 0.001 if z is not None else False

					if move_in_x or move_in_y or not go_above_safe_or_above:
						# use transition feed only for long moves
						# long_move is defined as if the distance exceeds the distance needed to accel and brake multiplied with 5
						long_move = self._calc_dist(x,y,z) > 5*self._calc_required_dist_for_feed(self._get_transition_feed())
						if long_move:
							self.invokeOnLinear(x,y,z,self._get_transition_feed())
						else:
							self.invokeOnLinear(x,y,z)
						return

			feed = self._get_rapid_feed()
			self._calc_time_for_linear_movement(x,y,z,feed)
			self.onRapid(x,y,z,feed)
			self._curr_position.update(x,y,z)

		def invokeOnDwell(self, _dwell):
			self._cycle_time += _dwell
			self.onDwell(_dwell)

		def invokeOnChangeTool(self,_tool):
			self.onChangeTool(_tool)


		#--------------------------------------------------
		# Postprocessor's entry functions
		#--------------------------------------------------

		# this will be called before any output
		def beforeExport(self) -> None:
			pass

		# this will be called after the last output
		def afterExport(self) -> None:
			pass

		# will be called before any machining operation i.e. Pocket Operation 
		def beforeOperation(self,operation) -> None:
			pass

		# will be called after any machining operation, i.e. Pocket Operation 
		def afterOperation(self, operation : CamOperation) -> None:
			pass

		# will be called when the active plane is changes 
		def onChangePlane(self, _plane : Plane) -> None:
			return

		# will be called for Rapid movements 
		def onRapid(self,_x,_y,_z, _feed=None) -> None:
			self.error(f'onRapid not implemented')

		# will be called for linear movements 
		def onLinear(self,_x, _y, _z, _feed) -> None:
			self.error(f'onLinear not implemented')
		
		# will be called for circular movements 
		def onCircular(self, clockwise, i, j, k, x, y, z, feed) -> None:
			self.error(f'onCircular not implemented')

		# will be called if a tool change is required 
		def onChangeTool(self, _tool) -> None:
			self.error(f'onChangeTool not implemented')

		def onSpindelOff(self) -> None:
			self.error(f'onSpindelOff not implemented')

		# will be called if a change in the spindle speed is required 
		def onSpindelSpeed(self, _speed, _clockwise) -> None:
			self.error(f'onSpindelSpeed not implemented')
		
		# will be called if the coolant has to changed 
		def onCoolant(self, _coolant) -> None:
			self.error(f'onCoolant not implemented')
		
		# will be called if the plane is changed 
		def onPlaneChange(self, _plane) -> None:
			self.error(f'onPlaneChange not implemented')

		def onDwell(self, _seconds) -> None:
			self.error(f'onDwell not implemented')

		def onDrillingCycle(self,cmdName,params) -> None:
			self.error(f"onDrillingCycle not implemented")

except Exception as e:
	raise Exception(f"Exception in base.py: {e}")
