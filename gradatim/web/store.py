"""
In-memory data store for the web frontend.

Manages jobs (problems), users, invite codes, and compute configurations.
All state is held in memory — restarts clear everything.
"""

import hashlib
import secrets
import time
import threading
import uuid


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

        # Seed some sample data
        self._seed()

    def _seed(self):
        """Seed initial demo data."""
        # Create a system user for seeded jobs
        sys_id = self.create_user("system", is_system=True)

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

        # Create a batch of invite codes
        for _ in range(5):
            self.create_invite(created_by=sys_id)

    # --- Users ---

    def create_user(self, handle: str, is_system: bool = False) -> str:
        user_id = str(uuid.uuid4())
        with self._lock:
            self._users[user_id] = {
                "id": user_id,
                "handle": handle,
                "is_system": is_system,
                "created_at": time.time(),
                "jobs_posted": 0,
                "jobs_claimed": 0,
                "jobs_solved": 0,
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

    # --- Invites ---

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
        Redeem an invite code and create a new user.

        Returns (success, message_or_user_id).
        """
        with self._lock:
            invite = self._invites.get(code)
            if not invite:
                return False, "Invalid invite code."
            if invite["redeemed_by"]:
                return False, "This invite code has already been used."

            # Check handle uniqueness
            for u in self._users.values():
                if u["handle"] == handle:
                    return False, "That handle is already taken."

        # Create user (releases and reacquires lock internally)
        user_id = self.create_user(handle)

        with self._lock:
            self._invites[code]["redeemed_by"] = user_id
            self._invites[code]["redeemed_at"] = time.time()

        return True, user_id

    # --- Jobs ---

    def create_job(self, posted_by: str, title: str, category: str,
                   description: str, params: dict) -> str:
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
            }
            user = self._users.get(posted_by)
            if user:
                user["jobs_posted"] += 1
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
            job["status"] = "claimed"
            job["claimed_by"] = user_id
            job["claimed_at"] = time.time()
            if user_id not in job["workers"]:
                job["workers"].append(user_id)
            user = self._users.get(user_id)
            if user:
                user["jobs_claimed"] += 1
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
                    user = self._users.get(job.get("claimed_by", ""))
                    if user:
                        user["jobs_solved"] += 1

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
        return {
            "total_jobs": total_jobs,
            "open_jobs": open_jobs,
            "solved_jobs": solved_jobs,
            "running_jobs": total_jobs - open_jobs - solved_jobs,
            "total_users": total_users,
            "active_invites": active_invites,
        }
