"""Tests for the single-instance lock."""

import pytest

from alerter.lockfile import AlreadyRunning, single_instance


def test_second_instance_is_blocked(tmp_path):
    lock = tmp_path / "x.lock"
    with single_instance(lock, wait_seconds=0.1):
        with pytest.raises(AlreadyRunning):
            with single_instance(lock, wait_seconds=0.1):
                pass


def test_lock_is_released_after_block(tmp_path):
    lock = tmp_path / "x.lock"
    with single_instance(lock, wait_seconds=0.1):
        pass
    # should be free to acquire again
    with single_instance(lock, wait_seconds=0.1):
        pass


def test_writes_pid(tmp_path):
    lock = tmp_path / "x.lock"
    with single_instance(lock, wait_seconds=0.1):
        assert lock.read_text().strip().isdigit()
