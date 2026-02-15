"""
In-memory data store for the web frontend.

Manages jobs (problems), users, invite codes, reputation, bounties,
and compute configurations.
All state is held in memory — restarts clear everything.
"""

import hashlib
import secrets
import time
import threading
import uuid


# ---------------------------------------------------------------------------
# Trust tiers — progressive access based on reputation
# ---------------------------------------------------------------------------
TIER_NEWCOMER = "newcomer"       # 0-49   — can view board, claim simple jobs
TIER_CONTRIBUTOR = "contributor"  # 50-199 — can post jobs, claim any job
TIER_TRUSTED = "trusted"         # 200-499 — can generate invites, vote on results
TIER_EXPERT = "expert"           # 500+   — can moderate, set bounties

TIER_THRESHOLDS = [
    (500, TIER_EXPERT),
    (200, TIER_TRUSTED),
    (50, TIER_CONTRIBUTOR),
    (0, TIER_NEWCOMER),
]

# Reputation rewards
REP_JOB_SOLVED = 25       # Solver gets this for completing a job
REP_CONTRIBUTION = 10     # Reward for valid partial work / result
REP_POST_JOB = 2          # Small reward for posting a job
REP_INVITE_BONUS = 5      # Bonus when your invitee first solves a job
REP_INVALID_RESULT = -50  # Penalty for submitting bad results
REP_INITIAL = 10          # Starting reputation for open registration
REP_INVITED = 50          # Starting reputation for invite-redeemed users

# Claim rate limiting
MAX_ACTIVE_CLAIMS_NEWCOMER = 1
MAX_ACTIVE_CLAIMS_CONTRIBUTOR = 3
MAX_ACTIVE_CLAIMS_TRUSTED = 10
MAX_ACTIVE_CLAIMS_EXPERT = 50


def _get_tier(reputation: int) -> str:
    """Get trust tier name for a given reputation score."""
    for threshold, tier in TIER_THRESHOLDS:
        if reputation >= threshold:
            return tier
    return TIER_NEWCOMER


def _max_active_claims(tier: str) -> int:
    """Max concurrent claimed (running) jobs for a given tier."""
    return {
        TIER_NEWCOMER: MAX_ACTIVE_CLAIMS_NEWCOMER,
        TIER_CONTRIBUTOR: MAX_ACTIVE_CLAIMS_CONTRIBUTOR,
        TIER_TRUSTED: MAX_ACTIVE_CLAIMS_TRUSTED,
        TIER_EXPERT: MAX_ACTIVE_CLAIMS_EXPERT,
    }.get(tier, 1)


class Store:
    """Thread-safe in-memory store for all web app state."""

    def __init__(self):
        self._lock = threading.Lock()

        # Jobs: uuid_str -> dict
        self._jobs: dict[str, dict] = {}

        # Users: uuid_str -> dict
        self._users: dict[str, dict] = {}

        # Sessions: token_str -> user_id
        self._sessions: dict[str, str] = {}

        # Invite codes: code_str -> dict
        self._invites: dict[str, dict] = {}

        # Compute configs: user_id -> dict
        self._compute_configs: dict[str, dict] = {}

        # Activity log: list of dicts (most recent first)
        self._activity: list[dict] = []

        # Seed some sample data
        self._seed()

    def _seed(self):
        """Seed initial demo data."""
        # Create a system user for seeded jobs
        sys_id = self.create_user("system", is_system=True, reputation=9999)

        self.create_job(
            posted_by=sys_id,
            title="Factor 5959",
            category="factorization",
            description="Find the prime factors of 5959. Known to be a semiprime.",
            params={"n": 5959},
        )
        self.create_job(
            posted_by=sys_id,
            title="Factor 988027 (two large primes)",
            category="factorization",
            description="Factor the product of two 3-digit primes: 988027. "
                        "Good test for Pollard's Rho.",
            params={"n": 988027},
        )
        self.create_job(
            posted_by=sys_id,
            title="Factor 1001 (three prime factors)",
            category="factorization",
            description="1001 has three prime factors. Decompose it completely.",
            params={"n": 1001},
        )

        # Goldbach conjecture
        self.create_job(
            posted_by=sys_id,
            title="Goldbach: decompose 1000000",
            category="goldbach",
            description="Express 1,000,000 as the sum of two primes. "
                        "The Goldbach conjecture (1742) remains unproven.",
            params={"n": 1000000},
        )

        # Collatz conjecture
        self.create_job(
            posted_by=sys_id,
            title="Collatz: sequence from 27",
            category="collatz",
            description="Compute the Collatz sequence starting at 27. "
                        "The 3n+1 conjecture (1937) is one of the most famous "
                        "unsolved problems: does every sequence reach 1?",
            params={"start": 27},
        )

        # Perfect numbers
        self.create_job(
            posted_by=sys_id,
            title="Perfect numbers in [1, 100000000]",
            category="perfect_numbers",
            description="Search for perfect numbers up to 100 million. "
                        "Only 51 are known. Whether odd perfect numbers "
                        "exist is open for 2000+ years.",
            params={"range_start": 1, "range_end": 100000000},
        )

        # Primality
        self.create_job(
            posted_by=sys_id,
            title="Is 2^127 - 1 prime?",
            category="primality",
            description="Test if the Mersenne number 2^127 - 1 is prime. "
                        "This was the largest known prime for 75 years.",
            params={"n": (2**127) - 1},
        )

        # Create a batch of invite codes (still useful for trust bootstrapping)
        for _ in range(5):
            self.create_invite(created_by=sys_id)

    # --- Users ---

    def create_user(self, handle: str, is_system: bool = False,
                    reputation: int | None = None,
                    invited_by: str | None = None) -> str:
        user_id = str(uuid.uuid4())
        if reputation is None:
            reputation = REP_INVITED if invited_by else REP_INITIAL
        with self._lock:
            self._users[user_id] = {
                "id": user_id,
                "handle": handle,
                "is_system": is_system,
                "created_at": time.time(),
                "reputation": reputation,
                "tier": _get_tier(reputation),
                "invited_by": invited_by,
                "jobs_posted": 0,
                "jobs_claimed": 0,
                "jobs_solved": 0,
                "jobs_failed": 0,
            }
            # Default compute config
            self._compute_configs[user_id] = {
                "backend": "local",  # "local", "openai", "anthropic", "custom"
                "api_key": "",
                "model_name": "",
                "endpoint_url": "",
                "max_threads": 4,
            }
        return user_id

    def register_user(self, handle: str) -> tuple[bool, str]:
        """
        Open registration — anyone can join without an invite.

        Returns (success, user_id_or_error_message).
        New users start at REP_INITIAL (newcomer tier).
        """
        handle = handle.strip()
        if not handle or len(handle) > 30:
            return False, "Handle must be 1-30 characters."
        if not handle.replace("_", "").replace("-", "").isalnum():
            return False, "Handle may only contain letters, numbers, _ and -."
        with self._lock:
            for u in self._users.values():
                if u["handle"] == handle:
                    return False, "That handle is already taken."
        user_id = self.create_user(handle, reputation=REP_INITIAL)
        self._log_activity("join", user_id, detail=f"{handle} joined the network")
        return True, user_id

    def get_user(self, user_id: str) -> dict | None:
        with self._lock:
            u = self._users.get(user_id)
            return dict(u) if u else None

    def get_user_by_handle(self, handle: str) -> dict | None:
        with self._lock:
            for u in self._users.values():
                if u["handle"] == handle:
                    return dict(u)
        return None

    def add_reputation(self, user_id: str, amount: int, reason: str = ""):
        """Add (or subtract) reputation and recalculate tier."""
        with self._lock:
            user = self._users.get(user_id)
            if not user:
                return
            user["reputation"] = max(0, user["reputation"] + amount)
            user["tier"] = _get_tier(user["reputation"])
        if reason:
            self._log_activity("reputation", user_id,
                               detail=f"{'+' if amount >= 0 else ''}{amount}: {reason}")

    def get_leaderboard(self, limit: int = 20) -> list[dict]:
        """Top users by reputation."""
        with self._lock:
            users = [dict(u) for u in self._users.values()
                     if not u["is_system"]]
        users.sort(key=lambda u: u["reputation"], reverse=True)
        return users[:limit]

    # --- Sessions ---

    def create_session(self, user_id: str) -> str:
        token = secrets.token_hex(32)
        with self._lock:
            self._sessions[token] = user_id
        return token

    def get_session_user(self, token: str) -> str | None:
        with self._lock:
            return self._sessions.get(token)

    def delete_session(self, token: str):
        with self._lock:
            self._sessions.pop(token, None)

    # --- Invites (optional trust boost) ---

    def create_invite(self, created_by: str) -> str:
        code = secrets.token_urlsafe(8)
        with self._lock:
            self._invites[code] = {
                "code": code,
                "created_by": created_by,
                "created_at": time.time(),
                "redeemed_by": None,
                "redeemed_at": None,
            }
        return code

    def list_invites(self, created_by: str | None = None) -> list[dict]:
        with self._lock:
            invites = list(self._invites.values())
        if created_by:
            invites = [i for i in invites if i["created_by"] == created_by]
        return sorted(invites, key=lambda x: x["created_at"], reverse=True)

    def redeem_invite(self, code: str, handle: str) -> tuple[bool, str]:
        """
        Redeem an invite code and create a new user with boosted reputation.

        Returns (success, message_or_user_id).
        """
        with self._lock:
            invite = self._invites.get(code)
            if not invite:
                return False, "Invalid invite code."
            if invite["redeemed_by"]:
                return False, "This invite code has already been used."
            for u in self._users.values():
                if u["handle"] == handle:
                    return False, "That handle is already taken."

        inviter_id = invite["created_by"]
        user_id = self.create_user(handle, reputation=REP_INVITED,
                                   invited_by=inviter_id)

        with self._lock:
            self._invites[code]["redeemed_by"] = user_id
            self._invites[code]["redeemed_at"] = time.time()

        self._log_activity("invite", user_id,
                           detail=f"{handle} joined via invite (boosted trust)")
        return True, user_id

    # --- Jobs ---

    def create_job(self, posted_by: str, title: str, category: str,
                   description: str, params: dict,
                   bounty: int = 0) -> str:
        job_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "title": title,
                "category": category,
                "description": description,
                "params": params,
                "posted_by": posted_by,
                "posted_at": now,
                "status": "open",         # open, claimed, running, solved, failed
                "claimed_by": None,
                "claimed_at": None,
                "result": None,
                "solved_at": None,
                "workers": [],            # list of user_ids contributing
                "compute_backend": None,  # what backend solved it
                "bounty": bounty,         # reputation bounty for solver
            }
            user = self._users.get(posted_by)
            if user:
                user["jobs_posted"] += 1
        if bounty > 0:
            self._log_activity("bounty", posted_by,
                               detail=f"Bounty of {bounty} rep on: {title}")
        return job_id

    def list_jobs(self, category: str | None = None,
                  status: str | None = None) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        if category:
            jobs = [j for j in jobs if j["category"] == category]
        if status:
            jobs = [j for j in jobs if j["status"] == status]
        return sorted(jobs, key=lambda x: x["posted_at"], reverse=True)

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def claim_job(self, job_id: str, user_id: str) -> tuple[bool, str]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False, "Job not found."
            if job["status"] != "open":
                return False, f"Job is already {job['status']}."

            user = self._users.get(user_id)
            if not user:
                return False, "User not found."

            # Rate limit: check active claims based on tier
            tier = user.get("tier", TIER_NEWCOMER)
            max_claims = _max_active_claims(tier)
            active = sum(
                1 for j in self._jobs.values()
                if j["claimed_by"] == user_id and j["status"] in ("claimed", "running")
            )
            if active >= max_claims:
                return False, (
                    f"You can have at most {max_claims} active job(s) "
                    f"at your current tier ({tier}). "
                    f"Complete or release existing jobs first."
                )

            job["status"] = "claimed"
            job["claimed_by"] = user_id
            job["claimed_at"] = time.time()
            if user_id not in job["workers"]:
                job["workers"].append(user_id)
            user["jobs_claimed"] += 1
        self._log_activity("claim", user_id,
                           detail=f"Claimed: {job['title']}")
        return True, "Job claimed."

    def update_job_status(self, job_id: str, status: str,
                          result: dict | None = None):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["status"] = status
                if result is not None:
                    job["result"] = result
                if status == "solved":
                    job["solved_at"] = time.time()
                    solver_id = job.get("claimed_by", "")
                    user = self._users.get(solver_id)
                    if user:
                        user["jobs_solved"] += 1
                        # Reputation reward
                        reward = REP_JOB_SOLVED + job.get("bounty", 0)
                        user["reputation"] += reward
                        user["tier"] = _get_tier(user["reputation"])
                        # Check if solver was invited — bonus to inviter
                        inviter_id = user.get("invited_by")
                        if inviter_id:
                            inviter = self._users.get(inviter_id)
                            if inviter:
                                inviter["reputation"] += REP_INVITE_BONUS
                                inviter["tier"] = _get_tier(inviter["reputation"])
                elif status == "failed":
                    solver_id = job.get("claimed_by", "")
                    user = self._users.get(solver_id)
                    if user:
                        user["jobs_failed"] += 1

    def add_worker(self, job_id: str, user_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job and user_id not in job["workers"]:
                job["workers"].append(user_id)

    # --- Compute Configs ---

    def get_compute_config(self, user_id: str) -> dict | None:
        with self._lock:
            cfg = self._compute_configs.get(user_id)
            return dict(cfg) if cfg else None

    def update_compute_config(self, user_id: str, config: dict):
        with self._lock:
            existing = self._compute_configs.get(user_id, {})
            for key in ("backend", "api_key", "model_name",
                        "endpoint_url", "max_threads"):
                if key in config:
                    existing[key] = config[key]
            self._compute_configs[user_id] = existing

    # --- Activity Log ---

    def _log_activity(self, kind: str, user_id: str, detail: str = ""):
        entry = {
            "kind": kind,
            "user_id": user_id,
            "detail": detail,
            "timestamp": time.time(),
        }
        with self._lock:
            self._activity.insert(0, entry)
            # Keep last 200 entries
            if len(self._activity) > 200:
                self._activity = self._activity[:200]

    def get_activity(self, limit: int = 30) -> list[dict]:
        with self._lock:
            return list(self._activity[:limit])

    # --- Stats ---

    def get_stats(self) -> dict:
        with self._lock:
            total_jobs = len(self._jobs)
            open_jobs = sum(1 for j in self._jobs.values() if j["status"] == "open")
            solved_jobs = sum(1 for j in self._jobs.values() if j["status"] == "solved")
            total_users = sum(
                1 for u in self._users.values() if not u["is_system"]
            )
            active_invites = sum(
                1 for i in self._invites.values() if not i["redeemed_by"]
            )
            total_bounties = sum(
                j.get("bounty", 0) for j in self._jobs.values()
                if j["status"] == "open"
            )
        return {
            "total_jobs": total_jobs,
            "open_jobs": open_jobs,
            "solved_jobs": solved_jobs,
            "running_jobs": total_jobs - open_jobs - solved_jobs,
            "total_users": total_users,
            "active_invites": active_invites,
            "total_bounties": total_bounties,
        }
