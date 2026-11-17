/**
 * A map icon as a signed distance field, so MapLibre can color it per feature
 * (`icon-color`) and draw a ring around it (`icon-halo-*`) without one image per color.
 * `inside(x, y)` says whether a pixel centre is part of the shape, in a `size` × `size`
 * box with y pointing down. 0.75 alpha marks the edge, as MapLibre expects.
 */
export function sdfIcon(
  size: number,
  inside: (x: number, y: number) => boolean,
): { width: number; height: number; data: Uint8Array } {
  const mask: boolean[] = [];
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) mask.push(inside(x + 0.5, y + 0.5));

  const data = new Uint8Array(size * size * 4);
  for (let i = 0; i < mask.length; i++) {
    // Distance to the nearest pixel on the other side of the edge (brute force: icons are tiny).
    let nearest = Infinity;
    for (let j = 0; j < mask.length; j++) {
      if (mask[j] === mask[i]) continue;
      const dx = (j % size) - (i % size);
      const dy = Math.floor(j / size) - Math.floor(i / size);
      nearest = Math.min(nearest, dx * dx + dy * dy);
    }
    const distance = (mask[i] ? 1 : -1) * (Math.sqrt(nearest) - 0.5);
    data.set([255, 255, 255, Math.max(0, Math.min(255, 192 + distance * 24))], i * 4);
  }
  return { width: size, height: size, data };
}
