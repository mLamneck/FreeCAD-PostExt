# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

try:
	import FreeCAD # type: ignore[import-not-found]

	from typing import Any, List
	import subprocess
	import sys
	import os

	def open_with_default_app(path : str):
		if sys.platform.startswith("win"):
			os.startfile(path)	# type: ignore[attr-defined]
		elif sys.platform.startswith("darwin"):
			subprocess.run(["open", path])   # macOS
		else:
			subprocess.run(["xdg-open", path])  # Linux

	def get_fc_version_str() -> str:
		v = FreeCAD.Version()
		return f"{v[0]}.{v[1]}.{v[2]}R{v[3]}"

	def remove_property_group(obj : Any, group_name : str):
		properties_to_remove : List[Any] = []

		for prop in obj.PropertiesList:
			if obj.getGroupOfProperty(prop) == group_name:
				properties_to_remove.append(prop)

		for prop in properties_to_remove:
			obj.removeProperty(prop)

except Exception as e:
	raise Exception(f"Exception in utils.py {e}")