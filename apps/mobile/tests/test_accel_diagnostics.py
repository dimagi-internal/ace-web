"""Hardware-acceleration (KVM vs TCG) parsing in the diagnostics probe.

A cold AVD boot that falls back to TCG (software CPU emulation) runs many
times slower than KVM — the leading hypothesis for multi-minute ensure_running
times. These assert the probe surfaces that signal."""
from apps.mobile.controller import _parse_diagnostics


def _stdout(*, kvm_section: str, emulator_log: str = "") -> str:
    return (
        "---ADB_DEVICES---\nList of devices attached\nemulator-5554\tdevice\n"
        "---EMULATOR_PROC---\n123 qemu-system-x86_64\n"
        "---RUNNER_SERVICE---\nactive\n"
        "---MARKER---\npresent\nmtime=0\n"
        "---RUNNER_LOG_TAIL---\n\n"
        "---EMULATOR_LOG_TAIL---\n" + emulator_log + "\n"
        "---KVM---\n" + kvm_section + "\n"
        "---END---\n"
    )


def test_accel_kvm_when_dev_kvm_present():
    diag = _parse_diagnostics(_stdout(kvm_section="dev_kvm=present\nnested=1"))
    assert diag.kvm_dev_present is True
    assert diag.kvm_nested == "1"
    assert diag.accel == "kvm"


def test_accel_tcg_when_dev_kvm_absent():
    diag = _parse_diagnostics(_stdout(kvm_section="dev_kvm=absent\nnested=unknown"))
    assert diag.kvm_dev_present is False
    assert diag.accel == "tcg"


def test_accel_tcg_when_emulator_log_shows_fallback():
    """The emulator's own error string is the strongest signal, even if
    /dev/kvm looks present (e.g. nested virt misconfigured)."""
    diag = _parse_diagnostics(_stdout(
        kvm_section="dev_kvm=present\nnested=0",
        emulator_log="x86_64 emulation currently requires hardware acceleration!",
    ))
    assert diag.accel == "tcg"


def test_accel_none_when_section_absent():
    """Older AMIs without the KVM probe leave accel unset, not a wrong guess."""
    stdout = (
        "---ADB_DEVICES---\nList of devices attached\nemulator-5554\tdevice\n"
        "---EMULATOR_LOG_TAIL---\n\n---END---\n"
    )
    diag = _parse_diagnostics(stdout)
    assert diag.accel is None
    assert diag.kvm_dev_present is None
