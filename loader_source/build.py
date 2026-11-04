"""Reproducible offline H9 build using the existing authenticated GNU toolchain."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'tools'))
import build_v100_greeting as base
from decode_adfu_adec import transform,key_table,linux

WORK=ROOT/'build/rom32k-h9/reviewed'
def sha(data):return hashlib.sha256(data).hexdigest()
def write(path,text):path.write_text(text,encoding='utf-8',newline='\n')
def symbols(text):
    return {parts[2]:int(parts[0],16) for line in text.splitlines()
            if len(parts:=line.split())==3 and parts[1].upper() in ('T','A','D')}

def build(out,header):
    out.mkdir(parents=True,exist_ok=False)
    lines=[]
    for n in range(0,32,4):
        word=int.from_bytes(header[n:n+4],'little')
        lines += [f'lui $t0, 0x{word>>16:04x}',f'ori $t0, $t0, 0x{word&65535:04x}','sw $t0, 0x88($t2)']
    write(out/'identity.inc','\n'.join(lines)+'\n')
    base.tool('as','-EL','-mips32','-I',linux(out),'-o',linux(out/'prefix.o'),linux(SOURCE/'prefix.S'))
    base.tool('ld','-EL','-T',linux(SOURCE/'prefix.ld'),'-Map',linux(out/'prefix.map'),'-o',linux(out/'prefix.elf'),linux(out/'prefix.o'))
    base.tool('objcopy','-O','binary',linux(out/'prefix.elf'),linux(out/'prefix.bin'))
    (out/'prefix.objdump.txt').write_bytes(base.tool('objdump','-d',linux(out/'prefix.elf')))
    listing=base.tool('nm','-n',linux(out/'prefix.elf')).decode()
    write(out/'symbols.txt',listing)
    data=(out/'prefix.bin').read_bytes()
    if len(data)!=2048:raise ValueError('fixed 2 KiB size required')
    encoded=transform(data,key_table(),decode=False)
    if transform(encoded,key_table())!=data:raise ValueError('codec roundtrip failed')
    (out/'prefix.encoded.bin').write_bytes(encoded)
    return data,encoded,symbols(listing)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,default=WORK)
    work=p.parse_args().output_dir.resolve()
    subprocess.run([sys.executable,str(ROOT/'loader/experimental_rom_prefix/runner.py'),'verify'],check=True,capture_output=True)
    actual=base.run(['sha256sum',base.TOOLS+'/binutils-mipsel-linux-gnu_2.42-2ubuntu1cross5_amd64.deb']).decode().split()[0]
    if actual!=base.PACKAGE_SHA:raise ValueError('toolchain package changed')
    recipe={'experiment':'v100-rom32k-h9-001','isa':'MIPS32-R1-LE','base':0xb4061000,'image_bytes':2048,'response_bytes':{'cpu':64,'chunk':80,'chunks':2048},'prefix_bytes':32768,'passes':2,
            'binutils_package_sha256':actual,'assembler_version':base.tool('as','--version').decode().splitlines()[0],
            'linker_version':base.tool('ld','--version').decode().splitlines()[0],
            'sources':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p.read_bytes()) for p in [SOURCE/'prefix.S',SOURCE/'prefix.ld',SOURCE/'build.py',ROOT/'tools/build_v100_greeting.py',ROOT/'tools/decode_adfu_adec.py']}}
    work.mkdir(parents=True,exist_ok=True)
    cookie=work/'cookie.hex'
    if not cookie.exists():
        with cookie.open('x') as f:f.write(secrets.token_hex(16)+'\n')
    nonce=bytes.fromhex(cookie.read_text().strip())
    if len(nonce)!=16:raise ValueError('cookie length')
    header=b'V100R901'+bytes.fromhex(sha(base.canonical(recipe)))[:8]+nonce
    a=build(work/'clean-a',header);b=build(work/'clean-b',header)
    if a!=b:raise ValueError('clean builds differ')
    # The independent native codec/source is already hash-pinned by H4's chain.
    native=work/'codec.c'
    write(native,(ROOT/'build/v100-greeting-h1/codec.c').read_text())
    base.run(['cc','-O1','-Wall','-Werror',linux(native),linux(ROOT/'build/adfu-adec-analysis/external/meta/actions/encrypt.c'),'-o',linux(work/'codec')])
    base.run([linux(work/'codec'),linux(work/'clean-a/prefix.bin'),linux(work/'native-encoded.bin')])
    if (work/'native-encoded.bin').read_bytes()!=a[1]:raise ValueError('native codec disagrees')
    report={'recipe':recipe,'header_hex':header.hex(),'plaintext_sha256':sha(a[0]),'encoded_sha256':sha(a[1]),'symbols':a[2],
            'two_clean_builds_identical':True,'native_codec_matches':True,'hardware_accessed':False}
    write(work/'build.json',json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
