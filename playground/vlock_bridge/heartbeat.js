'use strict';

// A duplicate response must not keep a frozen publisher looking Online.
class HeartbeatMonitor {
  constructor(timeoutMs = 5000) {
    this.timeoutMs = timeoutMs;
    this.counter = null;
    this.session = null;
    this.changedAt = null;
    this.available = false;
    this.failed = false;
    this.revision = null;
  }

  observe(data, now) {
    if (data.online !== true || !Number.isSafeInteger(data.heartbeat_counter) || data.heartbeat_counter < 0
        || typeof data.session_id !== 'string' || !data.session_id) {
      this.unavailable();
      return;
    }
    if (Number.isFinite(data.offline_after_seconds) && data.offline_after_seconds >= 5 && data.offline_after_seconds <= 180) {
      this.timeoutMs = data.offline_after_seconds * 1000;
    }
    if (data.session_id !== this.session || this.counter === null || data.heartbeat_counter > this.counter) {
      this.session = data.session_id;
      this.counter = data.heartbeat_counter;
      this.changedAt = now;
      this.available = true;
      this.failed = false;
    } else if (data.heartbeat_counter < this.counter) {
      this.unavailable();
    }
    this.revision = data.revision;
  }

  unavailable() { this.available = false; this.failed = true; }

  status(now) {
    const ageMs = this.changedAt === null ? null : Math.max(0, now - this.changedAt);
    return {
      online: this.available && ageMs !== null && ageMs < this.timeoutMs,
      waiting: this.changedAt === null && !this.failed,
      counter: this.counter, ageSeconds: ageMs === null ? null : Math.floor(ageMs / 1000),
      revision: this.revision
    };
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = {HeartbeatMonitor};
