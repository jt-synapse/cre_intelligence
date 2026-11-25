import type { Metadata } from "next";
import "./styles.css";
import "maplibre-gl/dist/maplibre-gl.css";
export const metadata: Metadata = {
  title: "CRE Intelligence · Research workspace",
  description: "Property research, evidence, and acquisition operations.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
