#!/usr/bin/env python3
"""
Clauver SIP Provisioning Script.

Automates the Twilio + LiveKit SIP trunk setup so you don't have to
click through two dashboards. You provide credentials and a phone number,
this script does the rest.

Usage:
    cd ~/.clauver && .venv/bin/python scripts/provision_sip.py
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import string
import sys
from pathlib import Path

# --- Ensure we can import from project root ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ENV_FILE = PROJECT_ROOT / ".env"


def _random_string(length: int, chars: str = string.ascii_lowercase + string.digits) -> str:
    return "".join(random.choices(chars, k=length))


def _print_header():
    print()
    print("╔═══════════════════════════════════════════════════╗")
    print("║  Clauver SIP Provisioning                        ║")
    print("║  Connects your Twilio number to LiveKit          ║")
    print("╚═══════════════════════════════════════════════════╝")
    print()
    print("  Before we start, you need:")
    print("    1. A Twilio account (twilio.com) with Account SID + Auth Token")
    print("    2. A LiveKit Cloud account (cloud.livekit.io) with URL + Key + Secret")
    print("    3. A phone number already purchased on Twilio")
    print()


def _input_secret(prompt: str) -> str:
    """Read a password echoing * per character. Falls back to silent input on error."""
    print(prompt, end="", flush=True)
    if os.name == "nt":
        import msvcrt
        chars = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                print()
                break
            elif ch == "\x08":
                if chars:
                    chars.pop()
                    print("\b \b", end="", flush=True)
            elif ch == "\x03":
                raise KeyboardInterrupt
            else:
                chars.append(ch)
                print("*", end="", flush=True)
        return "".join(chars)
    else:
        try:
            import termios, tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            chars = []
            try:
                tty.setraw(fd)
                while True:
                    ch = sys.stdin.read(1)
                    if ch in ("\r", "\n"):
                        print()
                        break
                    elif ch in ("\x7f", "\x08"):
                        if chars:
                            chars.pop()
                            print("\b \b", end="", flush=True)
                    elif ch == "\x03":
                        raise KeyboardInterrupt
                    else:
                        chars.append(ch)
                        print("*", end="", flush=True)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            return "".join(chars)
        except Exception:
            import getpass
            return getpass.getpass("")


def _input(prompt: str, secret: bool = False, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    full_prompt = f"  {prompt}{suffix}: "
    if secret:
        value = _input_secret(full_prompt)
    else:
        value = input(full_prompt)
    return value.strip() or default


def _check_twilio_installed():
    try:
        import twilio  # noqa: F401
        return True
    except ImportError:
        return False


def _install_twilio():
    print("  ⚠️  'twilio' package not found.")
    answer = _input("Install it now? [Y/n]") or "y"
    if answer.lower() != "y":
        print("  ❌ Cannot proceed without twilio. Install manually:")
        print(f"     {sys.executable} -m pip install twilio")
        sys.exit(1)
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "twilio"])
    print("  ✓ twilio installed")
    print()


def _validate_twilio(account_sid: str, auth_token: str):
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException

    try:
        client = Client(account_sid, auth_token)
        account = client.api.accounts(account_sid).fetch()
        print(f"  ✓ Connected to Twilio (Account: {account.friendly_name})")
        return client
    except TwilioRestException as e:
        print(f"  ❌ Twilio auth failed: {e.msg}")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ Cannot connect to Twilio: {e}")
        sys.exit(1)


def _validate_livekit(url: str, api_key: str, api_secret: str):
    # Set env vars so LiveKitAPI picks them up
    os.environ["LIVEKIT_URL"] = url
    os.environ["LIVEKIT_API_KEY"] = api_key
    os.environ["LIVEKIT_API_SECRET"] = api_secret
    print("  ✓ LiveKit credentials saved")


def _list_twilio_numbers(client) -> list:
    numbers = client.incoming_phone_numbers.list(limit=50)
    if not numbers:
        print("  ❌ No phone numbers found on your Twilio account.")
        print("     Buy one at: twilio.com/console/phone-numbers/search")
        sys.exit(1)
    return numbers


def _find_clauver_trunks(client) -> list:
    """Return all Clauver trunks on the Twilio account."""
    trunks = client.trunking.v1.trunks.list(limit=50)
    return [
        t for t in trunks
        if (t.friendly_name and "clauver" in t.friendly_name.lower())
        or (t.domain_name and "clauver" in t.domain_name.lower())
    ]


def _select_clauver_trunk(client, trunks: list):
    """Auto-select if one trunk, show a numbered menu if many. Returns trunk object."""
    if len(trunks) == 1:
        return trunks[0]

    print("  Multiple Clauver trunks found on your Twilio account:")
    for i, t in enumerate(trunks, 1):
        nums = client.trunking.v1.trunks(t.sid).phone_numbers.list(limit=3)
        num_str = ", ".join(n.phone_number for n in nums) or "no number"
        print(f"    {i}. {t.domain_name}  ({num_str})")
    print()
    raw = _input(f"Select trunk [1-{len(trunks)}]")
    try:
        choice = int(raw)
        if choice < 1 or choice > len(trunks):
            raise ValueError
    except ValueError:
        print("  ❌ Invalid selection.")
        sys.exit(1)
    return trunks[choice - 1]


def _create_twilio_trunk(client, phone_number_sid: str, phone_number: str):
    """Create Twilio SIP trunk with termination, credentials, and number assignment."""
    from twilio.base.exceptions import TwilioRestException

    # Generate unique domain and credentials
    domain_suffix = _random_string(6)
    domain_name = f"clauver-{domain_suffix}.pstn.twilio.com"
    sip_username = f"clauver_{_random_string(8)}"
    sip_password = _random_string(24, string.ascii_letters + string.digits)

    print(f"  Creating Twilio SIP trunk (random ID: {domain_name})...", end=" ", flush=True)

    # Create trunk (retry with different domain if taken)
    trunk = None
    for attempt in range(3):
        try:
            trunk = client.trunking.v1.trunks.create(
                friendly_name="Clauver Voice",
                domain_name=domain_name,
            )
            break
        except TwilioRestException as e:
            if "unique" in str(e).lower() or "already" in str(e).lower():
                domain_suffix = _random_string(6)
                domain_name = f"clauver-{domain_suffix}.pstn.twilio.com"
            else:
                raise

    if not trunk:
        print("✗")
        print("  ❌ Could not create trunk after 3 attempts.")
        sys.exit(1)
    print("✓")

    # Create credential list
    print("  Setting termination credentials...", end=" ", flush=True)
    cred_list = client.sip.credential_lists.create(friendly_name=f"Clauver SIP Auth {domain_suffix}")
    client.sip.credential_lists(cred_list.sid).credentials.create(
        username=sip_username, password=sip_password
    )
    # Associate with trunk
    client.trunking.v1.trunks(trunk.sid).credentials_lists.create(
        credential_list_sid=cred_list.sid
    )
    print("✓")

    # Assign phone number
    print("  Assigning phone number to trunk...", end=" ", flush=True)
    client.trunking.v1.trunks(trunk.sid).phone_numbers.create(
        phone_number_sid=phone_number_sid
    )
    print("✓")

    return {
        "trunk_sid": trunk.sid,
        "domain_name": domain_name,
        "sip_username": sip_username,
        "sip_password": sip_password,
        "phone_number": phone_number,
    }


def _add_twilio_origination(client, trunk_sid: str, livekit_sip_host: str):
    """Add origination URI to Twilio trunk so inbound PSTN calls route to LiveKit."""
    print("  Adding Twilio origination URI...", end=" ", flush=True)
    client.trunking.v1.trunks(trunk_sid).origination_urls.create(
        sip_url=f"sip:{livekit_sip_host}",
        priority=1,
        weight=1,
        enabled=True,
        friendly_name="LiveKit Inbound",
    )
    print("✓")


def _derive_livekit_sip_host(livekit_url: str) -> str:
    host = livekit_url.replace("wss://", "").replace("ws://", "").rstrip("/")
    return f"sip.{host}"


async def _create_livekit_trunk(domain_name: str, sip_username: str, sip_password: str, phone_number: str) -> str:
    """Create LiveKit outbound SIP trunk. Returns trunk ID."""
    from livekit import api
    from livekit.protocol.sip import CreateSIPOutboundTrunkRequest, SIPOutboundTrunkInfo

    print("  Creating LiveKit outbound trunk...", end=" ", flush=True)

    lkapi = api.LiveKitAPI()
    try:
        trunk_info = SIPOutboundTrunkInfo(
            name="Clauver Outbound",
            address=domain_name,
            numbers=[phone_number],
            auth_username=sip_username,
            auth_password=sip_password,
        )
        result = await lkapi.sip.create_outbound_trunk(
            CreateSIPOutboundTrunkRequest(trunk=trunk_info)
        )
        trunk_id = result.sip_trunk_id
        print("✓")
        return trunk_id
    except Exception as e:
        print("✗")
        print(f"  ❌ LiveKit error: {e}")
        sys.exit(1)
    finally:
        await lkapi.aclose()


async def _create_livekit_inbound(phone_number: str) -> tuple[str, str]:
    """Create LiveKit inbound trunk + dispatch rule. Returns (trunk_id, rule_id)."""
    from livekit import api
    from livekit.protocol.sip import (
        CreateSIPInboundTrunkRequest,
        SIPInboundTrunkInfo,
        CreateSIPDispatchRuleRequest,
        SIPDispatchRule,
        SIPDispatchRuleIndividual,
    )

    lkapi = api.LiveKitAPI()
    try:
        print("  Creating LiveKit inbound trunk...", end=" ", flush=True)
        trunk_result = await lkapi.sip.create_inbound_trunk(
            CreateSIPInboundTrunkRequest(trunk=SIPInboundTrunkInfo(
                name="Clauver Inbound",
                numbers=[phone_number],
            ))
        )
        trunk_id = trunk_result.sip_trunk_id
        print("✓")

        print("  Creating LiveKit dispatch rule...", end=" ", flush=True)
        rule_result = await lkapi.sip.create_dispatch_rule(
            CreateSIPDispatchRuleRequest(
                trunk_ids=[trunk_id],
                rule=SIPDispatchRule(
                    dispatch_rule_individual=SIPDispatchRuleIndividual(room_prefix="clauver-inbound-")
                ),
                name="Clauver Inbound Calls",
            )
        )
        rule_id = rule_result.sip_dispatch_rule_id
        print("✓")
        return trunk_id, rule_id
    except Exception as e:
        print("✗")
        print(f"  ❌ LiveKit inbound error: {e}")
        sys.exit(1)
    finally:
        await lkapi.aclose()


def _read_env_value(key: str) -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def _detect_existing_setup() -> dict | None:
    """Return existing outbound config from .env if fully populated, else None."""
    trunk_id = _read_env_value("SIP_OUTBOUND_TRUNK_ID")
    lk_url = _read_env_value("LIVEKIT_URL")
    lk_key = _read_env_value("LIVEKIT_API_KEY")
    lk_secret = _read_env_value("LIVEKIT_API_SECRET")
    if trunk_id and lk_url and lk_key and lk_secret:
        return {"trunk_id": trunk_id, "lk_url": lk_url, "lk_key": lk_key, "lk_secret": lk_secret}
    return None


def _update_env(values: dict[str, str]):
    """Update .env file, preserving existing content."""
    # Backup
    if ENV_FILE.exists():
        backup = ENV_FILE.with_suffix(".env.backup")
        backup.write_text(ENV_FILE.read_text())

    # Read existing
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []

    for key, value in values.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$")
        replaced = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(lines) + "\n")


def _confirm(summary: dict):
    print()
    print("  ─── Summary ───")
    print(f"    Twilio trunk:          {summary['domain_name']}")
    print(f"    Phone number:          {summary['phone_number']}")
    print(f"    LiveKit outbound:      {summary['livekit_trunk_id']}")
    if "inbound_trunk_id" in summary:
        print(f"    LiveKit inbound:       {summary['inbound_trunk_id']}")
        print(f"    LiveKit dispatch rule: {summary['dispatch_rule_id']}")
    print()
    answer = _input("Write to .env and finish? [Y/n]") or "y"
    return answer.lower() == "y"


async def _run_inbound_only(existing: dict):
    """Handle Journey B: add inbound to an already-configured outbound setup."""
    print("─── Adding Inbound Calls to Existing Setup ───")
    print()
    print("  Outbound is already configured. We'll add inbound only.")
    print("  Your existing outbound setup will not be touched.")
    print()

    # Need Twilio creds to mutate the trunk
    print("─── Twilio Credentials ───")
    print()
    twilio_sid = _input("Twilio Account SID")
    twilio_token = _input("Twilio Auth Token", secret=True)
    print()
    client = _validate_twilio(twilio_sid, twilio_token)
    print()

    # Restore LiveKit env vars from .env so lkapi picks them up
    os.environ["LIVEKIT_URL"] = existing["lk_url"]
    os.environ["LIVEKIT_API_KEY"] = existing["lk_key"]
    os.environ["LIVEKIT_API_SECRET"] = existing["lk_secret"]

    # Fetch trunk details from Twilio to get associated phone number
    print("  Looking up existing trunks...", end=" ", flush=True)
    try:
        trunks = _find_clauver_trunks(client)
        if not trunks:
            print("✗")
            print("  ❌ Could not find a Clauver trunk on Twilio.")
            print("     Run a full re-setup (option 2) to create one.")
            sys.exit(1)
        print("✓")
        print()
        trunk = _select_clauver_trunk(client, trunks)
        numbers = client.trunking.v1.trunks(trunk.sid).phone_numbers.list(limit=5)
    except SystemExit:
        raise
    except Exception as e:
        print("✗")
        print(f"  ❌ Could not fetch trunks: {e}")
        sys.exit(1)

    if not numbers:
        print("  ❌ No phone number found on selected trunk.")
        sys.exit(1)

    phone_number = numbers[0].phone_number
    print(f"  Using trunk: {trunk.domain_name} ({phone_number})")
    print()

    print("─── Provisioning Inbound ───")
    print()
    livekit_sip_host = _derive_livekit_sip_host(existing["lk_url"])
    _add_twilio_origination(client, trunk.sid, livekit_sip_host)
    inbound_trunk_id, dispatch_rule_id = await _create_livekit_inbound(phone_number)
    print()

    _update_env({"SIP_INBOUND_TRUNK_ID": inbound_trunk_id})
    print("  ✓ .env updated")
    print()
    print("═══════════════════════════════════════════════════════")
    print("✅ Inbound calling enabled!")
    print()
    print(f"  People can now call {phone_number} to reach LiveKit.")
    print(f"  Each caller gets their own room: clauver-inbound-...")
    print("═══════════════════════════════════════════════════════")
    print()


async def main():
    _print_header()

    # --- Check twilio package ---
    if not _check_twilio_installed():
        _install_twilio()

    # --- Detect existing outbound setup and offer inbound-only shortcut ---
    existing = _detect_existing_setup()
    if existing:
        print("  ✅ Detected existing outbound setup in .env")
        print()
        print("  What would you like to do?")
        print("    1. Add inbound calls to existing setup (keep outbound intact)")
        print("    2. Full re-setup (outbound + optional inbound)")
        print()
        choice = _input("Select [1/2]", default="1")
        print()
        if choice.strip() != "2":
            await _run_inbound_only(existing)
            return

    # --- Step 1: Twilio credentials ---
    print("─── Step 1: Twilio Credentials ───")
    print()
    twilio_sid = _input("Twilio Account SID")
    twilio_token = _input("Twilio Auth Token", secret=True)
    print()
    client = _validate_twilio(twilio_sid, twilio_token)
    print()

    # --- Step 2: LiveKit credentials ---
    print("─── Step 2: LiveKit Credentials ───")
    print()
    lk_url = _input("LiveKit URL (wss://...)")
    lk_key = _input("LiveKit API Key")
    lk_secret = _input("LiveKit API Secret", secret=True)
    print()
    _validate_livekit(lk_url, lk_key, lk_secret)
    print()

    # --- Step 3: Phone number ---
    print("─── Step 3: Phone Number ───")
    print()
    numbers = _list_twilio_numbers(client)
    print("  Your Twilio numbers:")
    for i, n in enumerate(numbers, 1):
        label = n.friendly_name or n.phone_number
        print(f"    {i}. {n.phone_number} ({label})")
    print()

    if len(numbers) == 1:
        choice = 1
        print(f"  Using: {numbers[0].phone_number}")
    else:
        raw = _input(f"Select number [1-{len(numbers)}]")
        try:
            choice = int(raw)
            if choice < 1 or choice > len(numbers):
                raise ValueError
        except ValueError:
            print("  ❌ Invalid selection.")
            sys.exit(1)
        print(f"  Using: {numbers[choice - 1].phone_number}")
    print()

    selected = numbers[choice - 1]

    # --- Check for existing trunk ---
    existing_trunks = _find_clauver_trunks(client)
    if existing_trunks:
        print(f"  ⚠️  Found {len(existing_trunks)} existing Clauver trunk(s) on Twilio:")
        for t in existing_trunks:
            print(f"       {t.domain_name} (SID: {t.sid})")
        print()
        answer = _input("Create a new one anyway? [y/N]") or "n"
        if answer.lower() != "y":
            print("  Keeping existing trunk. Run again if you want to recreate.")
            sys.exit(0)
        print()

    # --- Inbound opt-in ---
    print("─── Inbound Calls (Optional) ───")
    print()
    print("  Lets people call your Twilio number and reach LiveKit.")
    want_inbound = _input("Enable inbound calls? [y/N]", default="n").lower() == "y"
    print()

    # --- Step 4: Provision ---
    print("─── Step 4: Provisioning ───")
    print()

    twilio_result = _create_twilio_trunk(client, selected.sid, selected.phone_number)
    livekit_trunk_id = await _create_livekit_trunk(
        twilio_result["domain_name"],
        twilio_result["sip_username"],
        twilio_result["sip_password"],
        twilio_result["phone_number"],
    )

    inbound_trunk_id = None
    dispatch_rule_id = None
    if want_inbound:
        livekit_sip_host = _derive_livekit_sip_host(lk_url)
        _add_twilio_origination(client, twilio_result["trunk_sid"], livekit_sip_host)
        inbound_trunk_id, dispatch_rule_id = await _create_livekit_inbound(twilio_result["phone_number"])

    print()

    # --- Step 5: Confirm and save ---
    summary = {
        **twilio_result,
        "livekit_trunk_id": livekit_trunk_id,
        "livekit_url": lk_url,
        "livekit_key": lk_key,
        "livekit_secret": lk_secret,
    }
    if inbound_trunk_id:
        summary["inbound_trunk_id"] = inbound_trunk_id
        summary["dispatch_rule_id"] = dispatch_rule_id

    if not _confirm(summary):
        print("  Aborted. Trunks were created but .env was not updated.")
        print(f"  Your SIP_OUTBOUND_TRUNK_ID is: {livekit_trunk_id}")
        return

    print()
    print("─── Step 5: Saving to .env ───")
    print()
    env_updates = {
        "LIVEKIT_URL": lk_url,
        "LIVEKIT_API_KEY": lk_key,
        "LIVEKIT_API_SECRET": lk_secret,
        "SIP_OUTBOUND_TRUNK_ID": livekit_trunk_id,
    }
    if inbound_trunk_id:
        env_updates["SIP_INBOUND_TRUNK_ID"] = inbound_trunk_id
    _update_env(env_updates)
    print("  ✓ .env updated")
    print()

    print("═══════════════════════════════════════════════════════")
    print("✅ Done! Your Clauver is ready to make calls.")
    print()
    print(f"  Test: Tell Hermes \"Call {selected.phone_number} and say hello\"")
    if want_inbound:
        print(f"  Inbound: People can call {selected.phone_number} to reach LiveKit.")
    print("═══════════════════════════════════════════════════════")
    print()


if __name__ == "__main__":
    asyncio.run(main())
