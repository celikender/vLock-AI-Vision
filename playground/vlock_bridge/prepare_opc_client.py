"""Prepare ignored local client certificates; never log in or write remote tags."""
import argparse
import asyncio
import hashlib
import logging
from pathlib import Path


async def prepare(fetch_server=False):
    from asyncua import Client, ua
    from asyncua.crypto.cert_gen import setup_self_signed_certificate
    from cryptography.x509.oid import ExtendedKeyUsageOID
    root = Path(__file__).resolve().parent.parent / 'data' / 'vlock_bridge' / 'opcua'
    root.mkdir(parents=True, exist_ok=True)
    await setup_self_signed_certificate(root / 'client-key.pem', root / 'client.der',
        'urn:vlock:bridge:client', 'localhost', [ExtendedKeyUsageOID.CLIENT_AUTH],
        {'commonName': 'vLock Bridge Client'})
    print('Client certificate:', root / 'client.der')
    print('Client private key is stored locally; do not share it.')
    if fetch_server:
        endpoints = await Client('opc.tcp://127.0.0.1:62541/discovery', timeout=3).connect_and_get_server_endpoints()
        endpoint = Client.find_endpoint(endpoints,
            ua.MessageSecurityMode.SignAndEncrypt,
            'http://opcfoundation.org/UA/SecurityPolicy#Basic256Sha256')
        certificate = endpoint.ServerCertificate
        if not certificate:
            raise ValueError('Server did not advertise a certificate.')
        target = root / 'ignition-server.der'
        if target.exists() and target.read_bytes() != certificate:
            raise ValueError('Stored server certificate differs. Verify the Gateway certificate before replacing it.')
        target.write_bytes(certificate)
        print('Discovered server certificate:', target)
        print('SHA-256:', hashlib.sha256(certificate).hexdigest())
        print('Verify this fingerprint against the Gateway certificate before using it.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare local OPC UA client certificates')
    parser.add_argument('--fetch-server-certificate', action='store_true',
                        help='Discover the local Ignition public certificate; verify its fingerprint before trusting.')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(prepare(args.fetch_server_certificate))
    except Exception:
        parser.exit(1, 'Preparation incomplete. Check dependencies, the local Gateway and existing certificate files.\n')
