# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

import functools

class Logger:
	def __init__(self, indent_step: int = 2):
		self._indent = 0
		self._indent_step = indent_step

	def log(self, msg: str):
		print(" " * self._indent + msg)

	def __call__(self, func):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			self.log(f"-> {func.__name__}")
			self._indent += self._indent_step
			try:
					result = func(*args, **kwargs)
			finally:
					self._indent -= self._indent_step
					self.log(f"<- {func.__name__}")
			return result
		return wrapper

def shorten(val, maxlen=200):
	s = repr(val)
	if len(s) > maxlen:
			return s[:maxlen-3] + "..."
	return s

def objToList(obj,indent=""):
	l = [indent + type(obj).__name__]
	for attr in dir(obj):
		if attr.startswith('_'):
			continue
		try:
			val = getattr(obj, attr)
		except Exception as e:
			#l.append(f"obj.{attr} = <ERROR: {e}>")
			continue
		#l.append(type(val))
		if callable(val):
			continue
		try:
			l.append(f"{indent}obj.{attr} = {shorten(val)}")
		except:
			l.append(f"{indent}----------------------------------------------------------------------------------- {attr} not added")
	return l

def dump(obj):
	for attr in dir(obj):
		if not attr.startswith('_'):
			print("obj.%s = %r" % (attr, getattr(obj, attr)))


