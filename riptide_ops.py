"""
RIPTIDE: ISLAND OPS  (Python / Pygame edition)
A top-down 4v4 island capture-zone shooter.

Team RIPTIDE (you + 3 bots) vs Team CORSAIR (4 bots).
Hold zones A, B, C: each held zone = 2 pts/sec. Elimination = 3 pts.
First to 500 points, or the highest score when the 3:00 clock runs out, wins.

Controls:
  WASD move | Mouse aim | Left click fire | R reload | SHIFT sprint
  TAB standings | ESC pause | 1-4 pick loadout on the menu | ENTER deploy

Run:   pip install pygame
       python riptide_ops.py
Career (XP, wins, rank) is saved to riptide_career.json next to this file.
"""

import json
import math
import os
import random
import sys

import pygame

# ----------------------------------------------------------------- settings
SCREEN_W, SCREEN_H = 1280, 720
WORLD_W, WORLD_H = 2400, 1600
FPS = 60

WIN_SCORE = 500
ROUND_TIME = 180            # seconds
ZONE_POINTS_PER_SEC = 2
KILL_POINTS = 3
RESPAWN_TIME = 4.0
REGEN_DELAY = 3.0           # seconds out of combat before healing
REGEN_RATE = 25             # hp per second
CAPTURE_RATE = 35           # capture % per second per extra player
ZONE_RADIUS = 110
SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "riptide_career.json")

# colors
SEA_DEEP = (18, 78, 120)
SEA = (32, 120, 170)
SAND = (232, 210, 150)
GRASS = (92, 160, 80)
ROCK = (120, 118, 112)
PALM = (40, 110, 55)
TRUNK = (110, 75, 40)
WHITE = (245, 245, 245)
BLACK = (15, 15, 20)
RIPTIDE_C = (40, 200, 230)
CORSAIR_C = (240, 90, 60)
NEUTRAL_C = (210, 210, 210)
GOLD = (255, 200, 60)

TEAM_COLORS = {"RIPTIDE": RIPTIDE_C, "CORSAIR": CORSAIR_C, None: NEUTRAL_C}

# ----------------------------------------------------------------- loadouts
LOADOUTS = {
    "AR-24 ASSAULT":  dict(damage=14, rate=0.11, mag=30, reload=1.6, speed=900, spread=0.04, range=650, pellets=1),
    "VX-9 SMG":       dict(damage=9,  rate=0.06, mag=40, reload=1.4, speed=850, spread=0.08, range=480, pellets=1),
    "LR-7 MARKSMAN":  dict(damage=55, rate=0.75, mag=6,  reload=2.2, speed=1400, spread=0.005, range=1000, pellets=1),
    "BREAKER SHOTGUN": dict(damage=11, rate=0.8, mag=6,  reload=2.0, speed=800, spread=0.22, range=330, pellets=7),
}
LOADOUT_NAMES = list(LOADOUTS.keys())

RANKS = ["ROOKIE BRONZE I", "BRONZE II", "BRONZE III", "SILVER I", "SILVER II",
         "SILVER III", "GOLD I", "GOLD II", "GOLD III", "PLATINUM", "TIDE LEGEND"]


# ----------------------------------------------------------------- career save
def load_career():
    try:
        with open(SAVE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"xp": 0, "matches": 0, "wins": 0, "kills": 0, "captures": 0}


def save_career(c):
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(c, f, indent=2)
    except OSError:
        pass


def rank_for(xp):
    return RANKS[min(len(RANKS) - 1, xp // 500)]


# ----------------------------------------------------------------- helpers
def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def seg_circle_hit(p1, p2, c, r):
    """Does the segment p1->p2 pass within r of point c?"""
    (x1, y1), (x2, y2), (cx, cy) = p1, p2, c
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0:
        return dist(p1, c) <= r
    t = clamp(((cx - x1) * dx + (cy - y1) * dy) / l2, 0, 1)
    return dist((x1 + t * dx, y1 + t * dy), c) <= r


# ----------------------------------------------------------------- world
class Island:
    """Island made of overlapping sand blobs, with rocks and palms as cover."""

    def __init__(self, seed=8):
        rnd = random.Random(seed)
        cx, cy = WORLD_W / 2, WORLD_H / 2
        self.blobs = [(cx, cy, 620)]
        for _ in range(14):
            a = rnd.uniform(0, math.tau)
            d = rnd.uniform(250, 520)
            self.blobs.append((cx + math.cos(a) * d * 1.3, cy + math.sin(a) * d * 0.8, rnd.uniform(220, 360)))
        self.zones = {
            "A": (cx - 620, cy - 120),
            "B": (cx, cy + 60),
            "C": (cx + 620, cy - 80),
        }
        self.spawns = {"RIPTIDE": (cx - 900, cy + 120), "CORSAIR": (cx + 900, cy + 140)}
        # guarantee solid ground under spawns and zones, connected end to end
        path = [self.spawns["RIPTIDE"], self.zones["A"], self.zones["B"], self.zones["C"], self.spawns["CORSAIR"]]
        for (x1, y1), (x2, y2) in zip(path, path[1:]):
            for i in range(6):
                t = i / 5
                self.blobs.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, rnd.uniform(230, 300)))
        self.obstacles = []          # (x, y, radius, kind)
        tries = 0
        while len(self.obstacles) < 46 and tries < 2000:
            tries += 1
            x, y = rnd.uniform(200, WORLD_W - 200), rnd.uniform(200, WORLD_H - 200)
            r = rnd.uniform(26, 48)
            if not self.on_land(x, y, margin=40):
                continue
            if any(dist((x, y), z) < ZONE_RADIUS - 20 for z in self.zones.values()):
                continue
            if any(dist((x, y), s) < 120 for s in self.spawns.values()):
                continue
            if any(dist((x, y), (o[0], o[1])) < o[2] + r + 50 for o in self.obstacles):
                continue
            self.obstacles.append((x, y, r, rnd.choice(["rock", "palm", "palm"])))
        self.surface = self._render()

    def on_land(self, x, y, margin=0):
        return any(dist((x, y), (bx, by)) < br - margin for bx, by, br in self.blobs)

    def _render(self):
        surf = pygame.Surface((WORLD_W, WORLD_H))
        surf.fill(SEA_DEEP)
        for bx, by, br in self.blobs:
            pygame.draw.circle(surf, SEA, (int(bx), int(by)), int(br + 70))
        for bx, by, br in self.blobs:
            pygame.draw.circle(surf, SAND, (int(bx), int(by)), int(br))
        for bx, by, br in self.blobs:
            pygame.draw.circle(surf, GRASS, (int(bx), int(by)), int(br * 0.62))
        # voxel-ish grid overlay for that blocky look
        grid = pygame.Surface((WORLD_W, WORLD_H), pygame.SRCALPHA)
        for gx in range(0, WORLD_W, 40):
            pygame.draw.line(grid, (0, 0, 0, 18), (gx, 0), (gx, WORLD_H))
        for gy in range(0, WORLD_H, 40):
            pygame.draw.line(grid, (0, 0, 0, 18), (0, gy), (WORLD_W, gy))
        surf.blit(grid, (0, 0))
        return surf

    def blocks_shot(self, p1, p2):
        for x, y, r, _ in self.obstacles:
            if seg_circle_hit(p1, p2, (x, y), r * 0.85):
                return True
        return False


class Zone:
    def __init__(self, name, pos):
        self.name, self.pos = name, pos
        self.owner = None
        self.progress = 0.0      # -100 (CORSAIR) .. +100 (RIPTIDE)

    def update(self, dt, soldiers, game):
        r = sum(1 for s in soldiers if s.alive and s.team == "RIPTIDE" and dist(s.pos, self.pos) < ZONE_RADIUS)
        c = sum(1 for s in soldiers if s.alive and s.team == "CORSAIR" and dist(s.pos, self.pos) < ZONE_RADIUS)
        diff = r - c
        if diff == 0:
            return
        before = self.owner
        self.progress = clamp(self.progress + diff * CAPTURE_RATE * dt, -100, 100)
        if self.progress >= 100:
            self.owner = "RIPTIDE"
        elif self.progress <= -100:
            self.owner = "CORSAIR"
        elif (self.owner == "RIPTIDE" and self.progress <= 0) or (self.owner == "CORSAIR" and self.progress >= 0):
            self.owner = None
        if self.owner and self.owner != before:
            game.feed(f"{self.owner} captured zone {self.name}", TEAM_COLORS[self.owner])
            if self.owner == game.player.team and dist(game.player.pos, self.pos) < ZONE_RADIUS:
                game.player.captures += 1


class Bullet:
    def __init__(self, owner, pos, angle, w):
        self.owner = owner
        self.pos = list(pos)
        self.start = tuple(pos)
        self.vel = (math.cos(angle) * w["speed"], math.sin(angle) * w["speed"])
        self.damage = w["damage"]
        self.range = w["range"]
        self.dead = False

    def update(self, dt, game):
        old = tuple(self.pos)
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt
        new = tuple(self.pos)
        if dist(self.start, new) > self.range or game.island.blocks_shot(old, new):
            self.dead = True
            return
        for s in game.soldiers:
            if s.alive and s.team != self.owner.team and seg_circle_hit(old, new, s.pos, s.radius):
                s.hit(self.damage, self.owner, game)
                self.dead = True
                return


class Soldier:
    radius = 16

    def __init__(self, name, team, loadout, is_player=False):
        self.name, self.team, self.is_player = name, team, is_player
        self.set_loadout(loadout)
        self.kills = self.deaths = self.captures = 0
        self.alive = False
        self.respawn_timer = 0.0
        self.pos = [0.0, 0.0]
        self.angle = 0.0
        # bot brain
        self.goal = None
        self.think_timer = 0.0
        self.strafe = random.choice([-1, 1])

    def set_loadout(self, name):
        self.loadout = name
        self.weapon = LOADOUTS[name]
        self.ammo = self.weapon["mag"]

    def spawn(self, game):
        sx, sy = game.island.spawns[self.team]
        self.pos = [sx + random.uniform(-60, 60), sy + random.uniform(-80, 80)]
        self.hp = 100
        self.alive = True
        self.ammo = self.weapon["mag"]
        self.reload_t = 0.0
        self.cool = 0.0
        self.last_hurt = 99.0
        self.goal = None

    def hit(self, dmg, attacker, game):
        if not self.alive:
            return
        self.hp -= dmg
        self.last_hurt = 0.0
        attacker.last_hurt = min(attacker.last_hurt, 0.5)
        if self.hp <= 0:
            self.alive = False
            self.respawn_timer = RESPAWN_TIME
            self.deaths += 1
            attacker.kills += 1
            game.scores[attacker.team] += KILL_POINTS
            game.feed(f"{attacker.name} eliminated {self.name}", TEAM_COLORS[attacker.team])
            game.particles.burst(self.pos, TEAM_COLORS[self.team])

    # ---- movement with obstacle + shoreline collision
    def move(self, dx, dy, speed, dt, game):
        if dx == 0 and dy == 0:
            return
        l = math.hypot(dx, dy)
        dx, dy = dx / l * speed * dt, dy / l * speed * dt
        for axis in (0, 1):
            np = list(self.pos)
            np[axis] += dx if axis == 0 else dy
            if not game.island.on_land(np[0], np[1], margin=8):
                continue
            blocked = False
            for ox, oy, orad, _ in game.island.obstacles:
                if dist(np, (ox, oy)) < orad + self.radius:
                    blocked = True
                    break
            if not blocked:
                self.pos = np

    def try_fire(self, game):
        if self.reload_t > 0 or self.cool > 0:
            return
        if self.ammo <= 0:
            self.start_reload()
            return
        w = self.weapon
        muzzle = (self.pos[0] + math.cos(self.angle) * 22, self.pos[1] + math.sin(self.angle) * 22)
        for _ in range(w["pellets"]):
            game.bullets.append(Bullet(self, muzzle, self.angle + random.uniform(-w["spread"], w["spread"]), w))
        self.ammo -= 1
        self.cool = w["rate"]
        self.last_hurt = min(self.last_hurt, 1.0)   # firing counts as combat
        if self.ammo == 0:
            self.start_reload()

    def start_reload(self):
        if self.reload_t <= 0 and self.ammo < self.weapon["mag"]:
            self.reload_t = self.weapon["reload"]

    def update_common(self, dt):
        self.cool = max(0.0, self.cool - dt)
        self.last_hurt += dt
        if self.reload_t > 0:
            self.reload_t -= dt
            if self.reload_t <= 0:
                self.ammo = self.weapon["mag"]
        if self.last_hurt > REGEN_DELAY and self.hp < 100:
            self.hp = min(100, self.hp + REGEN_RATE * dt)

    # ---- simple bot AI
    def bot_update(self, dt, game):
        self.think_timer -= dt
        enemies = [s for s in game.soldiers if s.alive and s.team != self.team]
        target, best = None, 1e9
        for e in enemies:
            d = dist(self.pos, e.pos)
            if d < self.weapon["range"] * 0.9 and d < best and not game.island.blocks_shot(self.pos, e.pos):
                target, best = e, d

        if self.think_timer <= 0:
            self.think_timer = random.uniform(1.0, 2.5)
            self.strafe = random.choice([-1, 1])
            zones = list(game.zones.values())
            wanted = [z for z in zones if z.owner != self.team] or zones
            wanted.sort(key=lambda z: dist(self.pos, z.pos) + random.uniform(0, 400))
            z = wanted[0]
            self.goal = (z.pos[0] + random.uniform(-60, 60), z.pos[1] + random.uniform(-60, 60))

        speed = 190
        if target:
            aim = math.atan2(target.pos[1] - self.pos[1], target.pos[0] - self.pos[0])
            # bots aren't perfect shots
            self.angle = aim + random.uniform(-0.12, 0.12)
            self.try_fire(game)
            # strafe while fighting, drift toward goal
            perp = (math.cos(aim + math.pi / 2) * self.strafe, math.sin(aim + math.pi / 2) * self.strafe)
            gx, gy = (self.goal[0] - self.pos[0], self.goal[1] - self.pos[1]) if self.goal else (0, 0)
            gl = math.hypot(gx, gy) or 1
            self.move(perp[0] + gx / gl * 0.5, perp[1] + gy / gl * 0.5, speed * 0.8, dt, game)
        elif self.goal:
            gx, gy = self.goal[0] - self.pos[0], self.goal[1] - self.pos[1]
            if math.hypot(gx, gy) > 20:
                self.angle = math.atan2(gy, gx)
                before = tuple(self.pos)
                self.move(gx, gy, speed, dt, game)
                if dist(before, self.pos) < 0.5:   # stuck on cover: slide sideways
                    self.move(-gy * self.strafe, gx * self.strafe, speed, dt, game)
            if self.ammo < self.weapon["mag"] // 2:
                self.start_reload()


# ----------------------------------------------------------------- particles
class Particles:
    def __init__(self):
        self.items = []

    def burst(self, pos, color, n=18):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            sp = random.uniform(60, 220)
            self.items.append([pos[0], pos[1], math.cos(a) * sp, math.sin(a) * sp, 0.6, color])

    def update(self, dt):
        for p in self.items:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
        self.items = [p for p in self.items if p[4] > 0]

    def draw(self, surf, cam):
        for x, y, _, _, life, col in self.items:
            pygame.draw.rect(surf, col, (x - cam[0] - 3, y - cam[1] - 3, 6, 6))


# ----------------------------------------------------------------- game
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("RIPTIDE: Island Ops")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas,menlo,monospace", 18, bold=True)
        self.big = pygame.font.SysFont("consolas,menlo,monospace", 56, bold=True)
        self.mid = pygame.font.SysFont("consolas,menlo,monospace", 30, bold=True)
        self.career = load_career()
        self.loadout_idx = 0
        self.state = "menu"
        self.island = Island()

    # ---------- match setup
    def new_match(self):
        self.island = Island(seed=random.randint(1, 9999))
        self.zones = {n: Zone(n, p) for n, p in self.island.zones.items()}
        self.player = Soldier("YOU", "RIPTIDE", LOADOUT_NAMES[self.loadout_idx], is_player=True)
        allies = ["Marlin", "Reef", "Gale"]
        foes = ["Hook", "Brine", "Cutlass", "Kraken"]
        self.soldiers = [self.player]
        self.soldiers += [Soldier(n, "RIPTIDE", random.choice(LOADOUT_NAMES)) for n in allies]
        self.soldiers += [Soldier(n, "CORSAIR", random.choice(LOADOUT_NAMES)) for n in foes]
        for s in self.soldiers:
            s.spawn(self)
        self.bullets = []
        self.particles = Particles()
        self.scores = {"RIPTIDE": 0.0, "CORSAIR": 0.0}
        self.time_left = ROUND_TIME
        self.feed_items = []
        self.result = None
        self.state = "play"

    def feed(self, text, color):
        self.feed_items.append([text, color, 4.0])
        self.feed_items = self.feed_items[-5:]

    # ---------- main loop
    def run(self, max_frames=None):
        frames = 0
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit()
                    return
                self.handle_event(e)
            if self.state == "play":
                self.update(dt)
            self.draw()
            pygame.display.flip()
            frames += 1
            if max_frames and frames >= max_frames:
                pygame.quit()
                return

    def handle_event(self, e):
        if e.type != pygame.KEYDOWN:
            return
        if self.state == "menu":
            if pygame.K_1 <= e.key <= pygame.K_4:
                self.loadout_idx = e.key - pygame.K_1
            elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.new_match()
        elif self.state == "play":
            if e.key == pygame.K_ESCAPE:
                self.state = "pause"
            elif e.key == pygame.K_r and self.player.alive:
                self.player.start_reload()
        elif self.state == "pause":
            if e.key == pygame.K_ESCAPE:
                self.state = "play"
            elif e.key == pygame.K_q:
                self.state = "menu"
        elif self.state == "over":
            if e.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.state = "menu"

    # ---------- update
    def camera(self):
        return (clamp(self.player.pos[0] - SCREEN_W / 2, 0, WORLD_W - SCREEN_W),
                clamp(self.player.pos[1] - SCREEN_H / 2, 0, WORLD_H - SCREEN_H))

    def update(self, dt):
        keys = pygame.key.get_pressed()
        p = self.player
        cam = self.camera()
        if p.alive:
            mx, my = pygame.mouse.get_pos()
            p.angle = math.atan2(my + cam[1] - p.pos[1], mx + cam[0] - p.pos[0])
            dx = (keys[pygame.K_d] - keys[pygame.K_a])
            dy = (keys[pygame.K_s] - keys[pygame.K_w])
            sprint = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
            p.move(dx, dy, 300 if sprint else 210, dt, self)
            if pygame.mouse.get_pressed()[0] and not sprint:
                p.try_fire(self)

        for s in self.soldiers:
            if s.alive:
                s.update_common(dt)
                if not s.is_player:
                    s.bot_update(dt, self)
            else:
                s.respawn_timer -= dt
                if s.respawn_timer <= 0:
                    s.spawn(self)

        for b in self.bullets:
            b.update(dt, self)
        self.bullets = [b for b in self.bullets if not b.dead]
        self.particles.update(dt)

        for z in self.zones.values():
            z.update(dt, self.soldiers, self)
            if z.owner:
                self.scores[z.owner] += ZONE_POINTS_PER_SEC * dt

        for f in self.feed_items:
            f[2] -= dt
        self.feed_items = [f for f in self.feed_items if f[2] > 0]

        self.time_left -= dt
        if self.scores["RIPTIDE"] >= WIN_SCORE or self.scores["CORSAIR"] >= WIN_SCORE or self.time_left <= 0:
            self.end_match()

    def end_match(self):
        r, c = self.scores["RIPTIDE"], self.scores["CORSAIR"]
        self.result = "VICTORY" if r > c else "DEFEAT" if c > r else "DRAW"
        p = self.player
        xp = p.kills * 30 + p.captures * 50 + (200 if self.result == "VICTORY" else 60)
        self.earned_xp = xp
        self.career["xp"] += xp
        self.career["matches"] += 1
        self.career["wins"] += self.result == "VICTORY"
        self.career["kills"] += p.kills
        self.career["captures"] += p.captures
        save_career(self.career)
        self.state = "over"

    # ---------- drawing
    def text(self, s, pos, color=WHITE, font=None, center=False):
        img = (font or self.font).render(s, True, color)
        r = img.get_rect()
        if center:
            r.center = pos
        else:
            r.topleft = pos
        self.screen.blit(img, r)

    def draw(self):
        if self.state == "menu":
            return self.draw_menu()
        self.draw_world()
        self.draw_hud()
        if self.state == "pause":
            self.overlay("PAUSED", "ESC resume   Q quit to menu")
        elif self.state == "over":
            self.overlay(self.result, f"RIPTIDE {int(self.scores['RIPTIDE'])}  -  {int(self.scores['CORSAIR'])} CORSAIR"
                         f"    +{self.earned_xp} XP    ENTER to continue")
        if self.state == "play" and pygame.key.get_pressed()[pygame.K_TAB]:
            self.draw_standings()

    def draw_world(self):
        cam = self.camera()
        self.screen.blit(self.island.surface, (-cam[0], -cam[1]))
        # zones
        for z in self.zones.values():
            zx, zy = z.pos[0] - cam[0], z.pos[1] - cam[1]
            col = TEAM_COLORS[z.owner]
            ring = pygame.Surface((ZONE_RADIUS * 2, ZONE_RADIUS * 2), pygame.SRCALPHA)
            pygame.draw.circle(ring, (*col, 50), (ZONE_RADIUS, ZONE_RADIUS), ZONE_RADIUS)
            pygame.draw.circle(ring, (*col, 200), (ZONE_RADIUS, ZONE_RADIUS), ZONE_RADIUS, 4)
            self.screen.blit(ring, (zx - ZONE_RADIUS, zy - ZONE_RADIUS))
            if z.progress != 0:
                pc = RIPTIDE_C if z.progress > 0 else CORSAIR_C
                rect = pygame.Rect(zx - ZONE_RADIUS + 6, zy - ZONE_RADIUS + 6, ZONE_RADIUS * 2 - 12, ZONE_RADIUS * 2 - 12)
                pygame.draw.arc(self.screen, pc, rect, math.pi / 2, math.pi / 2 + math.tau * abs(z.progress) / 100, 6)
            self.text(z.name, (zx, zy), col, self.mid, center=True)
        # obstacles
        for x, y, r, kind in self.island.obstacles:
            sx, sy = int(x - cam[0]), int(y - cam[1])
            if kind == "rock":
                pygame.draw.rect(self.screen, ROCK, (sx - r, sy - r * 0.8, r * 2, r * 1.6), border_radius=6)
                pygame.draw.rect(self.screen, (90, 88, 84), (sx - r, sy - r * 0.8, r * 2, r * 1.6), 3, border_radius=6)
            else:
                pygame.draw.rect(self.screen, TRUNK, (sx - 7, sy - 7, 14, 14))
                for i in range(5):
                    a = i * math.tau / 5
                    pygame.draw.rect(self.screen, PALM, (sx + math.cos(a) * r * 0.6 - 12, sy + math.sin(a) * r * 0.6 - 12, 24, 24))
        # bullets
        for b in self.bullets:
            pygame.draw.line(self.screen, GOLD, (b.pos[0] - cam[0], b.pos[1] - cam[1]),
                             (b.pos[0] - cam[0] - b.vel[0] * 0.015, b.pos[1] - cam[1] - b.vel[1] * 0.015), 3)
        # soldiers (blocky voxel style)
        for s in self.soldiers:
            if not s.alive:
                continue
            sx, sy = s.pos[0] - cam[0], s.pos[1] - cam[1]
            col = TEAM_COLORS[s.team]
            gun = (sx + math.cos(s.angle) * 26, sy + math.sin(s.angle) * 26)
            pygame.draw.line(self.screen, BLACK, (sx, sy), gun, 6)
            pygame.draw.rect(self.screen, BLACK, (sx - 17, sy - 17, 34, 34))
            pygame.draw.rect(self.screen, col, (sx - 15, sy - 15, 30, 30))
            if s.is_player:
                pygame.draw.rect(self.screen, WHITE, (sx - 19, sy - 19, 38, 38), 2)
            # health bar
            pygame.draw.rect(self.screen, BLACK, (sx - 20, sy - 30, 40, 5))
            pygame.draw.rect(self.screen, (80, 230, 90), (sx - 20, sy - 30, 40 * s.hp / 100, 5))
            if not s.is_player:
                self.text(s.name, (sx, sy - 42), col, center=True)
        self.particles.draw(self.screen, cam)

    def draw_hud(self):
        # score bar
        mins, secs = divmod(max(0, int(self.time_left)), 60)
        pygame.draw.rect(self.screen, (0, 0, 0), (SCREEN_W / 2 - 260, 10, 520, 54), border_radius=8)
        self.text(f"RIPTIDE {int(self.scores['RIPTIDE'])}", (SCREEN_W / 2 - 245, 26), RIPTIDE_C)
        self.text(f"{mins}:{secs:02d}", (SCREEN_W / 2, 37), WHITE, self.mid, center=True)
        self.text(f"{int(self.scores['CORSAIR'])} CORSAIR", (SCREEN_W / 2 + 120, 26), CORSAIR_C)
        # zone chips
        for i, z in enumerate(self.zones.values()):
            x = SCREEN_W / 2 - 60 + i * 42
            pygame.draw.rect(self.screen, TEAM_COLORS[z.owner], (x, 70, 34, 26), border_radius=4)
            self.text(z.name, (x + 17, 83), BLACK, center=True)
        # player panel
        p = self.player
        pygame.draw.rect(self.screen, (0, 0, 0), (20, SCREEN_H - 90, 360, 70), border_radius=8)
        self.text(f"HP {int(p.hp) if p.alive else 0}", (36, SCREEN_H - 80), (80, 230, 90))
        ammo = "RELOADING..." if p.alive and p.reload_t > 0 else f"{p.ammo} / {p.weapon['mag']}"
        self.text(f"{p.loadout}   {ammo}", (36, SCREEN_H - 52))
        self.text(f"K {p.kills}  D {p.deaths}", (SCREEN_W - 170, SCREEN_H - 50))
        # feed
        for i, (t, c, _) in enumerate(self.feed_items):
            self.text(t, (SCREEN_W - 400, 110 + i * 24), c)
        if not p.alive:
            self.text(f"REDEPLOYING IN {max(0, p.respawn_timer):.1f}", (SCREEN_W / 2, SCREEN_H / 2), WHITE, self.mid, center=True)
        else:
            mx, my = pygame.mouse.get_pos()
            pygame.draw.circle(self.screen, WHITE, (mx, my), 10, 2)
            pygame.draw.line(self.screen, WHITE, (mx - 14, my), (mx + 14, my), 1)
            pygame.draw.line(self.screen, WHITE, (mx, my - 14), (mx, my + 14), 1)

    def draw_standings(self):
        pygame.draw.rect(self.screen, (0, 0, 0), (SCREEN_W / 2 - 300, 130, 600, 380), border_radius=10)
        self.text("STANDINGS", (SCREEN_W / 2, 160), GOLD, self.mid, center=True)
        y = 200
        for team in ("RIPTIDE", "CORSAIR"):
            for s in sorted([s for s in self.soldiers if s.team == team], key=lambda s: -s.kills):
                self.text(f"{s.name:<10} K {s.kills:<3} D {s.deaths:<3} CAP {s.captures}", (SCREEN_W / 2 - 260, y), TEAM_COLORS[team])
                y += 34
            y += 10

    def overlay(self, title, sub):
        shade = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 160))
        self.screen.blit(shade, (0, 0))
        self.text(title, (SCREEN_W / 2, SCREEN_H / 2 - 40), GOLD, self.big, center=True)
        self.text(sub, (SCREEN_W / 2, SCREEN_H / 2 + 30), WHITE, center=True)

    def draw_menu(self):
        self.screen.blit(self.island.surface, (-(WORLD_W - SCREEN_W) / 2, -(WORLD_H - SCREEN_H) / 2))
        shade = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        shade.fill((0, 20, 40, 170))
        self.screen.blit(shade, (0, 0))
        c = self.career
        self.text("RIPTIDE: ISLAND OPS", (SCREEN_W / 2, 110), GOLD, self.big, center=True)
        self.text("PARADISE. UNDER FIRE.  Island Domination: 3 zones, 4 vs 4, 3 minute rounds",
                  (SCREEN_W / 2, 170), WHITE, center=True)
        self.text("CHOOSE YOUR LOADOUT (1-4)", (SCREEN_W / 2, 240), WHITE, self.mid, center=True)
        for i, name in enumerate(LOADOUT_NAMES):
            w = LOADOUTS[name]
            sel = i == self.loadout_idx
            col = GOLD if sel else WHITE
            self.text(f"{'>' if sel else ' '} {i + 1}. {name:<16} DMG {w['damage']:<3} MAG {w['mag']:<3} RANGE {w['range']}",
                      (SCREEN_W / 2 - 330, 285 + i * 36), col)
        self.text(f"LEAGUE: {rank_for(c['xp'])}   XP {c['xp']}   MATCHES {c['matches']}   WINS {c['wins']}   KILLS {c['kills']}",
                  (SCREEN_W / 2, 460), RIPTIDE_C, center=True)
        self.text("ENTER TO DEPLOY", (SCREEN_W / 2, 530), GOLD, self.mid, center=True)
        self.text("WASD move  MOUSE aim  CLICK fire  R reload  SHIFT sprint  TAB standings  ESC pause",
                  (SCREEN_W / 2, 600), WHITE, center=True)
        self.text("Hold A, B or C for 2 pts/sec. Eliminations 3 pts. First to 500 wins.",
                  (SCREEN_W / 2, 630), WHITE, center=True)


if __name__ == "__main__":
    Game().run()
