import { ImageResponse } from "next/og";

export const dynamicParams = false;
export const generateStaticParams = () => [{ size: "192" }, { size: "512" }];

export async function GET(
  _: Request,
  { params }: { params: Promise<{ size: string }> },
) {
  const size = Number((await params).size);
  if (size !== 192 && size !== 512) return new Response(null, { status: 404 });
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        background: "#112f2a",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          height: "50%",
          gap: size * 0.045,
        }}
      >
        {[0.65, 1, 0.82].map((height) => (
          <div
            key={height}
            style={{
              width: size * 0.115,
              height: size * 0.5 * height,
              background: "#90c5a9",
              borderTop: size * 0.035 + "px solid #d3e9dd",
            }}
          />
        ))}
      </div>
    </div>,
    { width: size, height: size },
  );
}
