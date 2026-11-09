"""Occupancy mapping and frontier search from simulated range scans."""
from collections import deque
import math


MISSION_S = 60
ARENAS = ('north', 'south')
CELL = 0.10
X0, Y0 = -0.40, -0.80
COLS, ROWS = 24, 16
RANGE = 0.67
UNKNOWN, FREE, WALL = 0, 1, 2


class SearchMission:
    def __init__(self, mj, np, model_path, arena):
        side = 1 if arena == 'north' else -1
        # [center x, center y, full width, full depth]. The divider blocks
        # the starting line of sight and leaves one passage around its end.
        self.walls = [
            [-0.40, 0, 0.06, 1.66], [2.00, 0, 0.06, 1.66],
            [0.80, -0.80, 2.46, 0.06], [0.80, 0.80, 2.46, 0.06],
            [0.75, side * -0.35, 0.06, 0.90],
        ]
        self.beacon = [1.55, side * -0.06]
        spec = mj.MjSpec.from_file(str(model_path))
        for i, (x, y, width, depth) in enumerate(self.walls):
            spec.worldbody.add_geom(name=f'lab_wall_{i}', type=mj.mjtGeom.mjGEOM_BOX,
                                   pos=[x, y, .13], size=[width / 2, depth / 2, .13], group=5)
        spec.worldbody.add_geom(name='lab_beacon', type=mj.mjtGeom.mjGEOM_SPHERE,
                               pos=[*self.beacon, .14], size=[.068, 0, 0],
                               group=5, contype=0, conaffinity=0)
        self.model = spec.compile()
        self.beacon_id = self.model.geom('lab_beacon').id
        self.mj = mj
        self.mask = np.array([0, 0, 0, 0, 0, 1], dtype=np.uint8)
        self.hit = np.empty(1, dtype=np.int32)
        self.origin = np.array([0.0, 0.0, .14])
        self.direction = np.zeros(3)
        self.rays = [
            (math.cos(a), math.sin(a))
            for a in (i * math.tau / 60 for i in range(60))
        ]
        self.grid = [UNKNOWN] * (COLS * ROWS)
        self.visited = set()
        self.blocked = set()
        self.trail = []
        self.goal = self.waypoint = None
        self.found = False
        self.next_scan = 0
        self.command = (0.0, 0.0)

    @staticmethod
    def cell(x, y):
        col, row = math.floor((x - X0) / CELL), math.floor((y - Y0) / CELL)
        return (col, row) if 0 <= col < COLS and 0 <= row < ROWS else None

    @staticmethod
    def center(cell):
        col, row = cell
        return X0 + (col + 0.5) * CELL, Y0 + (row + 0.5) * CELL

    def get(self, cell):
        col, row = cell
        return self.grid[row * COLS + col]

    def mark(self, cell, value):
        if cell is None:
            return
        col, row = cell
        index = row * COLS + col
        if value == WALL and self.grid[index] != WALL:
            self.grid[index] = WALL
            # Inflate wall returns by the Duck's footprint and tracking margin.
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if dx * dx + dy * dy <= 4:
                        self.blocked.add((col + dx, row + dy))
        elif self.grid[index] == UNKNOWN:
            self.grid[index] = FREE

    def scan(self, data, x, y, yaw):
        self.origin[:2] = (x, y)
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        free, walls = set(), set()
        for dx, dy in self.rays:
            rx, ry = dx * cos_yaw - dy * sin_yaw, dx * sin_yaw + dy * cos_yaw
            self.direction[:2] = (rx, ry)
            distance = self.mj.mj_ray(self.model, data, self.origin, self.direction,
                                      self.mask, True, -1, self.hit)
            hit = 0 <= distance <= RANGE
            end = distance if hit else RANGE
            for step in range(math.ceil(end / .035)):
                d = step * .035
                free.add(self.cell(x + d * rx, y + d * ry))
            if hit and self.hit[0] == self.beacon_id:
                self.found = True
            elif hit:
                walls.add(self.cell(x + (end + .008) * rx, y + (end + .008) * ry))
        for cell in free - walls:
            self.mark(cell, FREE)
        for cell in walls:
            self.mark(cell, WALL)

    def route(self, current, x, y):
        if current is None:
            return
        queue = deque([current])
        parents = {current: None}
        candidates = []
        while queue:
            cell = queue.popleft()
            cx, cy = cell
            distance = math.dist((x, y), self.center(cell))
            if cell not in self.visited and cell not in self.blocked and distance > .17:
                # Prefer cells on the boundary of the observed map. A distant
                # unvisited floor cell is the fallback when walls hide a frontier.
                frontier = any(
                    0 <= cx + dx < COLS and 0 <= cy + dy < ROWS
                    and (cx + dx, cy + dy) not in self.blocked
                    and self.get((cx + dx, cy + dy)) == UNKNOWN
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )
                candidates.append((not frontier, distance, cell))
            for dx, dy in ((1, 0), (0, 1), (0, -1), (-1, 0)):
                neighbor = (cx + dx, cy + dy)
                if (neighbor not in parents and neighbor not in self.blocked
                        and 0 <= neighbor[0] < COLS and 0 <= neighbor[1] < ROWS
                        and self.get(neighbor) == FREE):
                    parents[neighbor] = cell
                    queue.append(neighbor)
        choices = {item[2] for item in candidates}
        if self.goal not in choices:
            self.goal = min(candidates)[2] if candidates else None
        path = []
        cell = self.goal
        while cell is not None and cell != current:
            path.append(cell)
            cell = parents[cell]
        self.waypoint = None
        for cell in reversed(path):
            wx, wy = self.center(cell)
            distance = math.hypot(wx - x, wy - y)
            if self.waypoint is not None and distance > .32:
                break
            steps = max(1, math.ceil(distance / .035))
            line = [self.cell(x + (wx - x) * i / steps, y + (wy - y) * i / steps)
                    for i in range(1, steps + 1)]
            if self.waypoint is not None and any(c in self.blocked or c not in parents for c in line):
                break
            self.waypoint = wx, wy

    def steer(self, data, root):
        x, y, _, w, qx, qy, qz = data.qpos[root:root + 7].tolist()
        yaw = math.atan2(2 * (w * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
        if data.time + 1e-7 >= self.next_scan:
            self.next_scan += .24
            self.scan(data, x, y, yaw)
            current = self.cell(x, y)
            if current is not None:
                self.visited.add(current)
            if self.goal is not None and math.dist((x, y), self.center(self.goal)) < .17:
                self.visited.add(self.goal)
                self.goal = None
            if not self.trail or math.dist((x, y), self.trail[-1]) > .055:
                self.trail.append([round(x, 3), round(y, 3)])
            if not self.found:
                self.route(current, x, y)
        if self.found or self.waypoint is None:
            self.command = (0.0, 0.0)
        else:
            wx, wy = self.waypoint
            error = (math.atan2(wy - y, wx - x) - yaw + math.pi) % math.tau - math.pi
            forward = .24 * max(0.0, math.cos(error)) if abs(error) < .95 else .0
            self.command = (forward, max(-1.0, min(1.0, 2.4 * error)))
        return self.command

    def snapshot(self):
        return dict(walls=self.walls, grid=''.join(map(str, self.grid)), cols=COLS, rows=ROWS,
                    origin=[X0, Y0], cell_m=CELL, trail=self.trail, waypoint=self.waypoint,
                    beacon=self.beacon if self.found else None,
                    mapped_percent=round(100 * (1 - self.grid.count(UNKNOWN) / len(self.grid))))
