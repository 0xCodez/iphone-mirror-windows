"""Keep WebDriverAgent up over Wi-Fi, so unplugging the cable does not stop clicks.

This process owns one no-admin tunnel to the phone and the test runner inside it.
The window reaches the helper at the phone's own address, port 8100. The tunnel
address is only usable inside this process.
"""
import asyncio
import sys
import traceback
import warnings

WDA_PORT = 8100


def _ipv4(addresses) -> str | None:
    ips = []
    for address in addresses:
        ip = getattr(address, "full_ip", None) or str(address)
        if ip.count(".") == 3 and ":" not in ip:
            ips.append(ip)
    private = [ip for ip in ips if ip.startswith(("192.168.", "10.", "172."))]
    if private:
        return private[0]
    return ips[0] if ips else None


async def _browse_ipv4(timeout: float) -> str | None:
    from pymobiledevice3.bonjour import browse_mobdev2

    for answer in await browse_mobdev2(timeout=timeout):
        ip = _ipv4(answer.addresses)
        if ip:
            return ip
    return None


async def pairing_services(browse, attempts=3, pause=1.0, on_miss=None):
    """One empty browse is a miss. Ask again before giving up."""
    found = []
    tries = max(1, attempts)
    for n in range(tries):
        found = list(await browse() or [])
        if found:
            return found
        if n + 1 < tries:
            if on_miss:
                on_miss()
            if pause:
                await asyncio.sleep(pause)
    return found


def find_phone_ipv4(timeout: float = 4.0) -> str | None:
    """IPv4 of an iPhone advertising on this LAN, or None. The cable is not required."""
    if sys.platform == "win32":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(_browse_ipv4(timeout))
    except Exception:
        return None


def _bundle_id(apps: dict) -> str | None:
    def is_wda(bundle, info):
        names = [bundle]
        if isinstance(info, dict):
            names += [str(info.get(k) or "") for k in ("CFBundleName", "CFBundleExecutable", "CFBundleDisplayName")]
        return any("webdriveragent" in n.lower() for n in names)

    candidates = [b for b, info in apps.items() if b and is_wda(b, info)]
    candidates.sort(key=lambda b: ("xctrunner" not in b.lower(), len(b)))
    return candidates[0] if candidates else None


async def _hold() -> None:
    from pymobiledevice3.remote import tunnel_service
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
    from pymobiledevice3.remote.tunnel_service import (
        TunnelProtocol,
        get_remote_pairing_tunnel_services,
        start_tunnel_over_remotepairing,
    )
    from pymobiledevice3.remote.userspace_tunnel import UserspaceDialPlane
    from pymobiledevice3.services.dvt.testmanaged.xcuitest import TestConfig, XCUITestService
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    tunnel_service.USE_USERSPACE_TUNNEL = True

    async def browse():
        return await get_remote_pairing_tunnel_services(bonjour_timeout=5)

    def again():
        print("Looking for the iPhone on Wi-Fi again.", flush=True)

    services = await pairing_services(browse, on_miss=again)
    if not services:
        print(
            "This PC has not paired with the iPhone over Wi-Fi yet. "
            "Plug the phone in once and try again.",
            flush=True,
        )
        return
    ipv4 = [s for s in services if s.hostname and ":" not in s.hostname]
    chosen = ipv4[0] if ipv4 else services[0]
    for extra in services:
        if extra is not chosen:
            await extra.close()
    print(f"PHONE {chosen.hostname}", flush=True)
    async with start_tunnel_over_remotepairing(chosen, protocol=TunnelProtocol.TCP) as result:
        tun = result.client.tun
        tun.set_peer(result.address)
        async with UserspaceDialPlane(tun, result.address) as dial:
            rsd = RemoteServiceDiscoveryService(
                (result.address, result.port),
                open_connection=dial.dial,
                auxiliary_metadata=result.auxiliary_metadata,
            )
            await rsd.connect()
            async with InstallationProxyService(lockdown=rsd) as install:
                bundle = _bundle_id(await install.get_apps(application_type="User"))
            if not bundle:
                print("WebDriverAgent is not installed on the iPhone.", flush=True)
                return
            print(f"BUNDLE {bundle}", flush=True)
            cfg = await TestConfig.create_for(rsd, bundle)
            print("RUNNER_START", flush=True)
            await XCUITestService(rsd).run(cfg)


def main() -> int:
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(_hold())
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
