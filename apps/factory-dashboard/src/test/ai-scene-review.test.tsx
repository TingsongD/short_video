import React from 'react';
import {render,screen,cleanup} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {AutoRunScreen} from '../features/autorun/AutoRunScreen';

afterEach(cleanup);
it.each([false,true])('retired review has no approval controls; reconciliation=%s',unknown=>{
  render(<AutoRunScreen seeds={[]} budgets={[]} runs={[{id:'old-run',stage:'blueprint',status:'paused',
    pause:{code:'ai_scene_review_unresolved',at:'old'},
    ai_scene_review:{status:'stopped',title:'AI scene review stopped',can_override:true},
    recovery:{title:unknown?'Reconcile earlier request':'Ready to continue',
      message:unknown?'Earlier outcome is unknown':'Scene review was removed',can_resume:!unknown}}]}
    act={vi.fn()} media={id=>id} onSelectExperiment={vi.fn()}/>);
  expect(screen.queryByRole('button',{name:'Manual fix'})).toBeNull();
  expect(screen.queryByRole('button',{name:'Proceed anyways'})).toBeNull();
  expect(screen.queryByText('AI scene review stopped')).toBeNull();
  expect(!!screen.queryByRole('button',{name:'Resume'})).toBe(!unknown);
});
