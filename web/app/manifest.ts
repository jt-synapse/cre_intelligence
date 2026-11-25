import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "CRE Intelligence Field Workspace",
    short_name: "CRE Field",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f5f7f4",
    theme_color: "#112f2a",
    icons: [
      {
        src: "/field-icon/192",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/field-icon/512",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
