# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 Mark Lamneck <mark.lamneck@gmail.com>

import math
from typing import List, Tuple

class Coordinate:
	def __init__(self,x=None,y=None,z=None):
		self.x : float | None
		self.y : float | None
		self.z : float | None
		self.reset()
		self.update(x,y,z)

	def update(self, x,y,z):
		if not x is None:
			self.x = x
		if not y is None:
			self.y = y
		if not z is None:
			self.z = z

	def is_valid(self):
		return self.x is not None and self.y is not None and self.z is not None

	def reset(self):
		self.x = None
		self.y = None
		self.z = None

	def __add__(self, other):
		if not isinstance(other, Coordinate):
			return NotImplemented

		return Coordinate(
			self.x + other.x if self.x is not None and other.x is not None else None,
			self.y + other.y if self.y is not None and other.y is not None else None,
			self.z + other.z if self.z is not None and other.z is not None else None,
		)

	def __str__(self):
		return f"({self.x}, {self.y}, {self.z})"


# =============================================================================
# Helper Functions – Math
# =============================================================================

def calc_circlular_sweep(c0 : float, c1 : float, s0 : float, s1 : float, e0 : float, e1 : float, clockwise : bool):
	"""
	calculate circular sweep in deg (0..360).

	c0,c1		: midpoint of circ relative to s0, s1 (CAM / I,J-Style)
	s0,s1 		: start coordinate (abs)
	e0,e1 		: end coordinate (abs)
	clockwise	: True = CW, False = CCW
	"""

	# abs midpoints
	mx = s0 + c0
	my = s1 + c1

	# tan(a)=gk/ak -> a = atan(gk/ak)
	phi_start = math.atan2(s1 - my, s0 - mx)
	phi_end   = math.atan2(e1 - my, e0 - mx)

	if clockwise:
		delta = phi_start - phi_end
	else:
		delta = phi_end - phi_start

	# norm to 0..2π
	delta = delta % (2 * math.pi)
	return delta
	#return math.degrees(delta)


def calc_radius(_e0 : float, _e1 : float, c0 : float, c1 : float):
	"""
	calc radius from reltive center i,j and endpoint _x, _y
	
	:param _e0: endpoint in direction 0
	:param _e1: endpoint in direction 1
	:param c0: relative center in direction 0
	:param c1: relative center in direction 1
	"""
	mx = _e0 + c0
	my = _e1 + c1
	x = _e0 - mx
	y = _e1 - my
	return math.sqrt(x*x+y*y)


def linearize_circular(_c0 : float,_c1 : float, 
					   _s0 : float,_s1 : float,_s2 : float, 
					   _e0 : float,_e1 : float,_e2 : float, 
					   _cw : bool, epsilon : float)  -> List[Tuple[float, float, float]]:
	"""
		Expands circle, helix or spiral into linear movements

		_c0..1	: centerpoint relative to start coordinate
		_s0..2	: start coordinate 0,1,2
		_e0..2	: end coordinate 0,1,2
		_cw		: True = CW, False = CCW
		epsilon	: allowed deviation from the midpoint of the chord to ideal circle
	"""

	# center point in absolute coordinates
	c0Abs = _c0 + _s0
	c1Abs = _c1 + _s1

	# start/end points for a circle around zero
	s0 = _s0 - c0Abs
	s1 = _s1 - c1Abs
	e0 = _e0 - c0Abs
	e1 = _e1 - c1Abs

	# calc start and end Radius and max radius
	R_start = math.sqrt(s0*s0 +s1*s1)
	R_end = math.sqrt(e0*e0 + e1*e1)
	if R_start < 1e-6:
		raise ValueError("Start radius must be > 0")

	#calc max angle for allowed deviation	
	R_max = R_start if R_start > R_end else R_end
	if epsilon <= 0 or epsilon >= 2*R_max:
		raise ValueError("epsilon must satisfy 0 < epsilon < 2*R")
	maxAngle = math.acos(1-epsilon/R_max)
	
	# tan(a)=gk/ak -> a = atan(gk/ak)
	phi_start = math.atan2(s1, s0)
	phi_end   = math.atan2(e1, e0)

	if _cw:
		angleDiff = phi_start - phi_end
	else:
		angleDiff = phi_end-phi_start
	if angleDiff < 0:
		angleDiff += 2*math.pi
	
	if angleDiff < 1e-12:
		return [(_s0,_s1,_s2), (_e0,_e1,_e2)]
	
	# calc number of chords and angle increment for each step
	if angleDiff > maxAngle:
		n = math.ceil(angleDiff/maxAngle)
		angleDiff = (angleDiff)/n
	else:
		n = 1
	if _cw:
		angleDiff = -angleDiff

	#calc increment for coordinate 2 and radius
	c2step = (_e2-_s2)/n
	Rstep = (R_end - R_start) / n
	
	chordEnds = [(_s0,_s1,_s2)]
	for i in range(1,n+1):
		angle = phi_start + angleDiff * i
		R = R_start + Rstep*i		
		p0 = R * math.cos(angle)
		p1 = R * math.sin(angle)
		p2 = _s2 + c2step*i
		chordEnds.append((p0+c0Abs, p1+c1Abs, p2))
	return chordEnds
