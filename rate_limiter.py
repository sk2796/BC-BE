import os
import time
import hashlib
from typing import Callable
from fastapi import Request, HTTPException, status

class RateLimiter:
    def __init__(self):
        self.records = {}
        
        # Load configurable limits from env
        self.strict_limit = int(os.getenv("RATE_LIMIT_STRICT_COUNT", "5"))
        self.strict_window = int(os.getenv("RATE_LIMIT_STRICT_WINDOW", "60")) # seconds
        
        self.moderate_limit = int(os.getenv("RATE_LIMIT_MODERATE_COUNT", "30"))
        self.moderate_window = int(os.getenv("RATE_LIMIT_MODERATE_WINDOW", "60"))
        
        self.loose_limit = int(os.getenv("RATE_LIMIT_LOOSE_COUNT", "120"))
        self.loose_window = int(os.getenv("RATE_LIMIT_LOOSE_WINDOW", "60"))
        
        # Load configurable salts for key anonymization
        self.ip_salt = os.getenv("IP_SALT", "default_ip_salt_123")
        self.account_salt = os.getenv("ACCOUNT_SALT", "default_account_salt_456")
        self.global_salt = os.getenv("GLOBAL_SALT", "default_global_salt_789")

    def _hash_key(self, raw_key: str, salt: str) -> str:
        """Anonymize the key (IP or Account ID) using the configured salt."""
        return hashlib.sha256(f"{salt}:{raw_key}".encode("utf-8")).hexdigest()

    def _clean_old_records(self, hashed_key: str, window: int, current_time: float):
        """Remove timestamps older than the configured window."""
        if hashed_key in self.records:
            self.records[hashed_key]['timestamps'] = [
                ts for ts in self.records[hashed_key]['timestamps']
                if current_time - ts < window
            ]

    def _is_rate_limited_exponential(self, hashed_key: str, max_attempts: int, base_delay: int = 1) -> bool:
        """
        Implements exponential backoff instead of a hard lockout.
        If the number of attempts exceeds max_attempts, calculate a required wait time.
        """
        current_time = time.time()
        
        if hashed_key not in self.records:
            self.records[hashed_key] = {'timestamps': [], 'failures': 0, 'last_attempt': 0}
            
        record = self.records[hashed_key]
        
        # Reset backoff if there's been no activity for a long time (e.g., 15 minutes)
        if current_time - record['last_attempt'] > 900:
            record['failures'] = 0
            
        record['last_attempt'] = current_time
        
        # Calculate backoff delay if limit exceeded
        if record['failures'] >= max_attempts:
            # Exponential backoff: base_delay * (2 ^ (failures - max_attempts))
            exponent = min(record['failures'] - max_attempts, 10) # Cap at 10 to prevent absurd delays
            required_wait = base_delay * (2 ** exponent)
            
            time_since_last = current_time - record['timestamps'][-1] if record['timestamps'] else 0
            
            if time_since_last < required_wait:
                retry_after = max(1, int(required_wait - time_since_last))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many attempts. Please try again in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)}
                )
        
        # If we reach here, request is allowed.
        record['timestamps'].append(current_time)
        return False

    def reset_all(self):
        """Reset all rate limit tracking records (useful for tests)."""
        self.records.clear()

    def _is_rate_limited_standard(self, hashed_key: str, limit: int, window: int) -> bool:
        """Standard fixed-window rate limiter."""
        current_time = time.time()
        
        if hashed_key not in self.records:
            self.records[hashed_key] = {'timestamps': [], 'failures': 0, 'last_attempt': 0}
            
        self._clean_old_records(hashed_key, window, current_time)
        
        if len(self.records[hashed_key]['timestamps']) >= limit:
            retry_after = window
            if self.records[hashed_key]['timestamps']:
                # Calculate time until the oldest request in the window expires
                oldest = self.records[hashed_key]['timestamps'][0]
                retry_after = int(window - (current_time - oldest))
                
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Please try again later.",
                headers={"Retry-After": str(max(1, retry_after))}
            )
            
        self.records[hashed_key]['timestamps'].append(current_time)
        return False

    def check_strict(self, request: Request, identifier: str = None):
        """Strict limits for auth routes, per-IP and per-account with exponential backoff."""
        client_ip = request.client.host if request.client else "unknown"
        hashed_ip = self._hash_key(client_ip, self.ip_salt)
        
        # Check IP limit
        self._is_rate_limited_exponential(hashed_ip, self.strict_limit)
        
        # Check Account limit if provided
        if identifier:
            hashed_account = self._hash_key(identifier, self.account_salt)
            self._is_rate_limited_exponential(hashed_account, self.strict_limit)
            
    def check_moderate(self, request: Request):
        """Moderate limits for public endpoints (per IP)."""
        client_ip = request.client.host if request.client else "unknown"
        hashed_ip = self._hash_key(client_ip, self.ip_salt)
        self._is_rate_limited_standard(hashed_ip, self.moderate_limit, self.moderate_window)

    def check_loose(self, request: Request, identifier: str = None):
        """Loose limits for authenticated user actions."""
        # Use account if available, otherwise IP
        if identifier:
            hashed_key = self._hash_key(identifier, self.account_salt)
        else:
            client_ip = request.client.host if request.client else "unknown"
            hashed_key = self._hash_key(client_ip, self.ip_salt)
            
        self._is_rate_limited_standard(hashed_key, self.loose_limit, self.loose_window)

    def report_auth_failure(self, request: Request, identifier: str = None):
        """Increment failure count for exponential backoff on auth routes."""
        client_ip = request.client.host if request.client else "unknown"
        hashed_ip = self._hash_key(client_ip, self.ip_salt)
        
        if hashed_ip in self.records:
            self.records[hashed_ip]['failures'] += 1
            
        if identifier:
            hashed_account = self._hash_key(identifier, self.account_salt)
            if hashed_account in self.records:
                self.records[hashed_account]['failures'] += 1

    def report_auth_success(self, request: Request, identifier: str = None):
        """Reset failure count on successful auth."""
        client_ip = request.client.host if request.client else "unknown"
        hashed_ip = self._hash_key(client_ip, self.ip_salt)
        
        if hashed_ip in self.records:
            self.records[hashed_ip]['failures'] = 0
            
        if identifier:
            hashed_account = self._hash_key(identifier, self.account_salt)
            if hashed_account in self.records:
                self.records[hashed_account]['failures'] = 0

# Global instance
limiter = RateLimiter()

# FastAPI Dependencies
def strict_limiter(request: Request):
    # If the route expects JSON, we can't easily extract the username here without consuming the body.
    # We'll just limit by IP for the strict dependency, and manually call check_strict(request, email) in the route if needed.
    limiter.check_strict(request)
    
def moderate_limiter(request: Request):
    limiter.check_moderate(request)
    
def loose_limiter(request: Request):
    limiter.check_loose(request)
