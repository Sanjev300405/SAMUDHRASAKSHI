import { useEffect } from 'react';
import type { AISTrack, CandidateScore } from '../lib/types';
import { assertClean } from '../lib/lexicon';
import { mmsi as fmtMmsi, pct, timeOfDay, titleCaseWord as titleCase, vesselType } from '../lib/format';

interface Props {
  candidate: CandidateScore;
  track: AISTrack | undefined;
  isTopRanked: boolean;
}

export default function VerdictLine({ candidate, track, isTopRanked }: Props) {
  const vt = vesselType(track?.vessel_type ?? null);
  const id = fmtMmsi(track?.mmsi ?? null);
  const release = candidate.best_release;

  const headline = release
    ? `${isTopRanked ? 'Strongest association' : `${titleCase(candidate.association_level)} association`}: ${vt} ${id}. A release from its ${timeOfDay(release.time)} position would have placed ${pct(release.hit_rate)} of the oil inside the slick the satellite actually saw.`
    : `No drift-compatible release point was found for this vessel.`;

  const meta = `${titleCase(candidate.association_level)} association · ${titleCase(candidate.evidence_strength)} evidence · ${titleCase(candidate.uncertainty)} uncertainty`;

  useEffect(() => {
    assertClean(headline, 'VerdictLine.headline');
    assertClean(meta, 'VerdictLine.meta');
  }, [headline, meta]);

  return (
    <div className="verdict-line">
      <p className="verdict-line__headline">
        {release ? (
          <>
            {isTopRanked ? 'Strongest association' : `${titleCase(candidate.association_level)} association`}:{' '}
            <span className="num">{vt} {id}</span>. A release from its <span className="num">{timeOfDay(release.time)}</span> position
            would have placed <span className="num">{pct(release.hit_rate)}</span> of the oil inside the slick the satellite actually saw.
          </>
        ) : (
          headline
        )}
      </p>
      <p className="verdict-line__meta">{meta}</p>
    </div>
  );
}
