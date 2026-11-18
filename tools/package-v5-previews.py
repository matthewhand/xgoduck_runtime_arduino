"""Refresh Duck Lab print bundles and rendered previews from the adjacent V5 hardware checkout."""
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

ROOT=Path(__file__).resolve().parents[1]
HARDWARE=ROOT.parent/'xgoduck_hardware'/'accessories'
ASSETS=ROOT/'assets'/'sim'
TEETH=HARDWARE/'v5-dino-beak'/'screw-teeth'
FACE=HARDWARE/'v5-face-plates'/'magnetic'
TAIL=HARDWARE/'v5-raptor-tail'
ARMS=TAIL/'necklace'
RUNNERS=TAIL/'roll-shoe-cover'
REAR=HARDWARE/'v5-slide-on-backpack'/'removable-rails'


def bundle(name,root,patterns):
    paths=sorted({path for pattern in patterns for path in root.glob(pattern) if path.is_file()})
    with ZipFile(ASSETS/name,'w',compression=ZIP_DEFLATED,compresslevel=6) as archive:
        for path in paths:
            archive.write(path,path.relative_to(root))


def refresh_guard_and_teeth():
    guard=HARDWARE/'v5-slide-on-backpack'/'rounded-guard'
    teeth=HARDWARE/'v5-dino-beak'/'coprint'
    for name in ['guard-recovery.webp','guard-front-left.webp','guard-roulade.webp']:
        shutil.copyfile(guard/'media'/name,ASSETS/name)
    shutil.copyfile(guard/'before-after.png',ASSETS/'guard-cad.png')
    shutil.copyfile(teeth/'figures/coprint-teeth.png',ASSETS/'coprint-teeth.png')
    bundle('rounded-guard-kit.zip',guard,['README.md','rounded-protective-cover.stl','fit.json','trials.json','release-angles.json','launch-times.json','before-after.png'])
    bundle('coprint-teeth-kit.zip',teeth,['README.md','print/*.3mf','fit.json','figures/*.png'])


def main():
    refresh_guard_and_teeth()
    copies={
        FACE/'off-and-on.png':'magnetic-face.png', FACE/'chin-hatch.png':'beard-hatch.png',
        FACE/'magnetic-section.png':'mask-magnetic-section.png', TEETH/'figures/screw-teeth.png':'screw-teeth.png',
        REAR/'rear-configurations.png':'rear-configurations.png',
        ARMS/'bare-and-worn.png':'claws-on-duck.png', ARMS/'three-claw-necklace.png':'necklace-claws.png', ARMS/'three-claw-turntable.webp':'necklace-claws.webp',
    }
    for source,destination in copies.items():
        shutil.copyfile(source,ASSETS/destination)
    bundle('mask-beard-fit.zip',FACE.parent,['*.md','*.json','*.py','*.png','print/*.stl'])
    bundle('magnetic-face-kit.zip',FACE,['*.md','*.json','*.png','print/*.stl'])
    bundle('screw-cheek-teeth.zip',TEETH,['*.md','fit.json','figures/*.png','print/*.stl'])
    bundle('three-claw-necklace.zip',ARMS,['*.md','*.stl','*.json','*.png'])
    prefixes=[REAR.relative_to(HARDWARE).as_posix()+'/',RUNNERS.relative_to(HARDWARE).as_posix()+'/']
    patterns=[prefixes[0]+p for p in ['README.md','print/*.stl','rear-configurations.png','plain-guard-roll.json']]
    patterns.extend(prefixes[1]+p for p in ['README.md','*.stl','fit.json','right-recovery.json'])
    bundle('removable-rear-kit.zip',HARDWARE,patterns)


if __name__=='__main__':main()
