import { describe, expect, it } from "vitest";
import { buildCaptionAndFootageVariants } from "../features/experiments/variation";

describe("caption and footage variants", () => {
  it("changes one scoped picture and caption while preserving shared footage", () => {
    const segments = Array.from({ length: 5 }, (_, i) => ({
      id: `b${i}`,
      target: { start_frame: i * 30, end_frame: (i + 1) * 30 },
      picture: { artifact_id: "art:source", source_in_s: i },
      captions: [],
    }));
    const beats = segments.map((segment) => ({
      id: segment.id,
      visual_event: `event ${segment.id}`,
    }));

    const variants = buildCaptionAndFootageVariants(segments, beats);

    expect(variants.map((variant) => variant.key)).toEqual(["B", "C", "D"]);
    expect(variants.map((variant) => variant.factor)).toEqual(["hook", "body", "ending"]);
    expect(variants.map((variant) => variant.allowed_fields)).toEqual([
      ["captions", "picture"],
      ["captions", "picture"],
      ["captions", "picture"],
    ]);

    variants.forEach((variant) => {
      const changed = variant.segments.filter((segment, index) =>
        JSON.stringify(segment) !== JSON.stringify(segments[index]));
      expect(changed).toHaveLength(1);
      expect(changed[0].picture.request.kind).toBe("video");
      expect(changed[0].picture.request.prompt).toContain("original or authorized characters");
      expect(changed[0].captions).toHaveLength(1);
      expect(variant.regions).toEqual([changed[0].target]);
    });

    expect(segments.every((segment) => segment.picture.artifact_id === "art:source")).toBe(true);
  });
});
