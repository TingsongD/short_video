import React from "react";
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RunProgress } from "../features/autorun/AutoRunScreen";

afterEach(cleanup);
it('reports measured all-frame coverage without guessing an unknown total',()=>{
  const {rerender}=render(<RunProgress run={{id:'flash',status:'running',stage:'video_analysis',
    source_analysis:{stage:'visual',state:'processing',encoded_frames:256,decoded_frames:300,
      processed_audio_samples:480000,audio_status:'measured',rhythm_status:'unreliable',jev_mode:'shadow',jev_status:'waiting',repairs_used:1,clarifications_used:0}}}/>);
  expect(screen.getByText(/256 frames encoded/)).toBeTruthy();
  expect(screen.getByText(/Total frame count not yet verified/)).toBeTruthy();
  expect(screen.queryByRole('progressbar',{name:'Source frame coverage'})).toBeNull();
  expect(screen.getByText(/Rhythm: unreliable/)).toBeTruthy();
  rerender(<RunProgress run={{id:'flash',status:'running',stage:'video_analysis',
    source_analysis:{stage:'understanding',state:'waiting',encoded_frames:300,total_frames:300,audio_status:'absent',
      next_attempt_at:'2026-09-21T12:00:00Z',updated_at:'2026-09-21T11:59:00Z',jev_mode:'shadow',jev_status:'unknown_retained'}}}/>);
  expect(screen.getByRole('progressbar',{name:'Source frame coverage'})).toHaveAttribute('value','300');
  expect(screen.getByText(/Unknown Jev outcome retained/)).toBeTruthy();
  expect(screen.getByText(/Audio: absent/)).toBeTruthy();
  expect(screen.getByText(/Next attempt: 2026/)).toBeTruthy();
});
it('shows a slow operation id, elapsed time, last observation and next poll', () => {
  render(<RunProgress run={{id:'r',status:'running',stage:'footage',provider_wait:{
    reason:'remote_unfinished',elapsed_s:600,operation_id:'operations/123',
    last_observed_at:'2026-09-22T12:00:08Z',next_poll_at:'2026-09-22T12:00:40Z'}}}/>);
  const wait = screen.getByRole('region', {name:'Provider wait'});
  expect(wait.textContent).toMatch(/600s elapsed/);
  expect(wait.textContent).toMatch(/operations\/123/);
  expect(wait.textContent).toMatch(/2026-09-22T12:00:08Z/);
  expect(wait.textContent).toMatch(/Next poll: 2026-09-22T12:00:40Z/);
});
it('shows provider backoff as waiting, not a failed or completed run', () => {
  const run = {id:'r',status:'running',stage:'footage',state:{provider_wait:{reason:'analysis_throttled'}}};
  const {rerender} = render(<RunProgress run={run}/>);
  expect(screen.getByText(/Google is busy/)).toBeTruthy();
  expect(screen.queryByText(/Paused — needs attention/)).toBeNull();
  rerender(<RunProgress run={{...run,state:{}}}/>);
  expect(screen.queryByText(/Google is busy/)).toBeNull();
});
it("shows the blocked stage and measured stage progress", () => {
  render(<RunProgress run={{id:"r",status:"paused",stage:"video_analysis",
    progress:[{stage:"intake",outcome:"done"},{stage:"evidence",outcome:"done"}],
    pause:{code:"analysis_failed",detail:"loader_failed",action:"Resolve then Resume"}}}/>);
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("2");
  expect(screen.getByText(/Paused — needs attention/)).toBeTruthy();
  expect(screen.getByText(/loader_failed/)).toBeTruthy();
});
it("does not count historical stages ahead of a rewind", () => {
  const {rerender}=render(<RunProgress run={{id:"r",status:"running",stage:"evidence",
    progress:[{stage:"intake",outcome:"done"},{stage:"compose",outcome:"done"}]}}/>);
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("1");
  rerender(<RunProgress run={{id:"r",status:"succeeded",stage:"done"}}/>);
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("17");
  expect(screen.getByText(/does not mean published or delivered/)).toBeTruthy();
});
