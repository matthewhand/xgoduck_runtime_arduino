const groutGap = .005;

function tiles(prefix, size) {
  return Array.from({length:12}, (_, index) => ({
    name:`${prefix}_${index}`,
    size:[size-groutGap, size-groutGap, .003],
    center:[.13+(index%4-.5)*size, (Math.floor(index/4)-1)*size, .0015],
  }));
}

export const SKATE_SURFACES = {
  flat: [],
  tiles: tiles('tile', .45),
  'tiles-xl': tiles('tile_xl', .60),
  carpet: [],
  bumps: [
    {name:'bump_6mm', size:[.022,.26,.006], center:[.115,0,.003]},
    {name:'bump_12mm', size:[.027,.26,.012], center:[.255,0,.006]},
  ],
};

export function skateTerrainXml() {
  // Reserve a different contact bit for the inactive geoms. The active
  // preset adds affinity for the robot's collision bit at runtime.
  return Object.values(SKATE_SURFACES).flat().map(({name,size,center}) =>
    `<geom name="${name}" type="box" pos="${center.join(' ')}" size="${size.map(v=>v/2).join(' ')}" contype="8" conaffinity="0" condim="3"/>`,
  ).join('\n');
}
