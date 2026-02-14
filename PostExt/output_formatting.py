# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

try:
	from typing import TypedDict, Unpack, NotRequired, List, Dict, cast
	import math
	from .post_properties import Properties, Property
	from .wrappers import CamOperation

	class Resettable():
		def reset(self):
			pass

	class Format:
		def __init__(self, prefix : str = "", scale : float = 1, decimals : int = 0):
			self.prefix = prefix
			self.scale = scale
			self.decimals = decimals
		
		def format(self, _value):
			if _value is None: 
				return ""
				
			scaled = _value * self.scale
			return f"{self.prefix}{scaled:.{self.decimals}f}"

		def formatraw(self, _value):
			scaled = _value * self.scale
			return f"{scaled:.{self.decimals}f}"

	class OutputParams(TypedDict):
		format: NotRequired[Format]
		force: NotRequired[bool]

	class OutputVariable(Resettable):
		def __init__(self, **kwargs: Unpack[OutputParams]):
			self.formatter = cast(Format, kwargs.get("format", Format()))
			self.force = kwargs.get("force",False)
			self.lastValue = None
			self.min = 1e12
			self.max = -1e12

		def reset(self):
			self.lastValue = None

		def getMin(self):
			return self.formatter.formatraw(self.min)

		def getMax(self):
			return self.formatter.formatraw(self.max)
			
		def _output(self, value):
			self.lastValue = value
			if value < self.min:
				self.min = value
			if value > self.max:
				self.max = value
			return self.formatter.format(value)

		@property
		def value(self):
			assert self.lastValue is not None, "value not assigned"
			return self.lastValue

		def format(self, value):
			if value is None:
				if self.force:
					raise Exception(f"Toutputter: force=true but no value given for {self.formatter.prefix}")
				return ""
			if self.lastValue is None:
				return self._output(value)
			if math.isclose(value, self.lastValue, rel_tol=1e-6, abs_tol=1e-9) and not self.force:
				return ""            
			return self._output(value)

	class Coolant():
		def __init__(self, id: str, on : str | List, off : str | List):
			self.id = id
			self.on = on
			self.off = off
			self.state = 0
			
	class CoolantManager(Resettable):
		def __init__(self, *coolants : Coolant):
			self.coolantOpts : Dict[str,Coolant] = {}
			for c in coolants:
				self.coolantOpts[c.id] = c

		def appendCmds(self, currCmds, newCmds):
			if isinstance(newCmds, list):
				currCmds.extend(newCmds)
			else:
				currCmds.append(newCmds)

		def setCoolant(self, _c : str):
			if _c is None or _c == "None":
				return []
			if not _c in self.coolantOpts:
				raise RuntimeError(f"coolant option {_c} not implemented")

			cmds = []
			for k in self.coolantOpts:
				v = self.coolantOpts[k]
				if v.id == _c:
					if v.state == 0:
						v.state = 1
						self.appendCmds(cmds,v.on)
				elif v.state == 1:
					v.state = 0
					self.appendCmds(cmds,v.off)
			return cmds

		def disableCoolant(self):
			cmds = []
			for k in self.coolantOpts:
				v = self.coolantOpts[k]
				if v.state == 1:
					v.state = 0
					self.appendCmds(cmds,v.off)
			return cmds
		
		def reset(self):
			self.disableCoolant()

	class Codeblock:
		class Ctx:
			def __init__(self,_properties : Properties):
				self.last_written_was_sep = False
				self.seq = _properties.sequenceStart.value
				self.Lines = []
				self.seq_format = "N{:d} "
				self.properties = _properties

		def __init__(self, cmt_format : str):
			self.cmt_format = cmt_format
			self.content = []
			
		def createSection(self):
			cb = Codeblock(self.cmt_format)
			self.content.append(cb)
			return cb
				
		def write(self, _line):
			self.content.append(_line)

		def writeBlock(self, *args):
			line = " ".join(str(a) for a in args if a not in (None, ""))
			if not line:
				raise Exception("line empty")
			self.write(line)
			
		def writeBlocks(self, _list):
			for l in _list:
				self.writeBlock(l)

		def writeSeparation(self):
			self.content.append(0)

		def writeComment(self, *args):
			line = " ".join(str(a) for a in args if a not in (None, ""))
			self.write(self.cmt_format.format(line))

		def _appendLine(self, ctx : Ctx, _line : str):
			if ctx.properties.writeSeqNumbers.value:
				ctx.Lines.append(ctx.seq_format.format(ctx.seq) + _line)
				ctx.seq += ctx.properties.sequenceInc.value
			else:
				ctx.Lines.append(_line)

		def _toString(self, ctx : Ctx):
			for c in self.content:
				if isinstance(c, Codeblock):
					c._toString(ctx)
				elif isinstance(c, int):
					if ctx.last_written_was_sep == False:
						self._appendLine(ctx,self.cmt_format.format("--------------------------------------------------------------"))
						ctx.last_written_was_sep = True
				else:
					self._appendLine(ctx,c)
					ctx.last_written_was_sep = False
			return "\n".join(ctx.Lines)

	class Outstream(Codeblock):
		def __init__(self, cmt_format : str):
			self.properties = Properties(
				writeSeqNumbers = Property(
					title = "Write Sequence Numbers",
					value = True,
					group = "Format"
				),
				sequenceStart = Property(
					title = "Sequence Start",
					value = 10,
					group = "Format"
				),
				sequenceInc = Property(
					title = "Sequence Increment",
					value = 5,
					group = "Format"
				),
			)
			super().__init__(cmt_format)

		def toString(self):
			return self._toString(self.Ctx(self.properties))

	class Warning:
		def __init__(self, job : CamOperation, text : str):
			self._operation = job
			self._text = text
			self.Fcount = 1

		def __str__(self):
			return f"{self._operation.getLabel()}: ({self.Fcount}) {self._text}"

	class Warnings:
		def __init__(self):
			self.Fitems : List[Warning] = []

		def add(self,_newW : Warning):
			for w in self.Fitems:
				if w._operation == _newW._operation and w._text == _newW._text:
					w.Fcount+=1
					return
			self.Fitems.append(_newW)

		def count(self):
			return len(self.Fitems)

		def __iter__(self):
			return iter(self.Fitems)

except Exception as e:
	raise Exception(f"exception in post_properties.py: {e}")


