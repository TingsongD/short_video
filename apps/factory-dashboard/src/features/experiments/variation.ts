type Row = Record<string, any>;

const FACTORS = ["hook", "body", "ending"] as const;
const VISUAL_DIRECTIONS = [
  "Use a tighter opening composition, an immediate expressive reaction, and more energetic camera blocking to strengthen the first-second hook.",
  "Use an alternate demonstration or B-roll angle with clearer action, prop interaction, and visual contrast to improve the explanation.",
  "Use an alternate payoff composition with a stronger final reaction and a clear open-loop ending image.",
] as const;

/**
 * Build B/C/D as controlled caption + footage treatments.
 * Unchanged segments retain A's picture binding and therefore deduplicate;
 * only the declared treatment region receives a new generation request.
 */
export function buildCaptionAndFootageVariants(segments: Row[], beats: Row[]) {
  const positions = [0, Math.floor(segments.length / 2), segments.length - 1];

  return ["B", "C", "D"].map((key, i) => {
    const pos = positions[i];
    const changed = structuredClone(segments);
    const segment = changed[pos];
    const beat = beats.find((item) => item.id === segment.id) || {};
    const subject = beat.visual_event || `${FACTORS[i]} beat ${segment.id}`;

    segment.captions = [{
      text: `Write your ${FACTORS[i]} caption`,
      ...segment.target,
    }];
    segment.picture = {
      request: {
        kind: "video",
        mode: "t2v",
        prompt: [
          "Vertical 9:16 social-video footage with original or authorized characters only; no on-screen text and no logos.",
          `Depict ${subject}.`,
          VISUAL_DIRECTIONS[i],
          "Keep the control's topic, meaning, approximate pacing, and overall visual world so the treatment remains comparable.",
        ].join(" "),
        settings: { aspect: "9:16" },
      },
    };

    return {
      key,
      factor: FACTORS[i],
      regions: [segment.target],
      segments: changed,
      hypothesis: `A coordinated ${FACTORS[i]} footage and caption treatment will improve retention while all other regions remain fixed.`,
      primary_metric: "retention",
      allowed_fields: ["captions", "picture"],
      dependent_fields: [],
    };
  });
}
