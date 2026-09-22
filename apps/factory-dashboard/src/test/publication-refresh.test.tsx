import React from 'react';
import {render,screen,fireEvent,cleanup} from '@testing-library/react';
import {afterEach,it,expect} from 'vitest';
import {PublishingScreen} from '../features/publishing/PublishingScreen';
afterEach(cleanup);
it('opened publication follows current status and selection',()=>{
  const selected={id:'exp',revision:1,variants:[{id:'exp:A',variant_key:'A'}]};
  const publication={id:'pub',variant_plan_id:'exp:A',platform:'youtube',status:'scheduled'};
  const props={selected,reviewer:'qa',act:async()=>{}};
  const {rerender}=render(<PublishingScreen {...props} data={{publications:[publication]}}/>);
  fireEvent.click(screen.getByText('open'));
  expect(screen.getByText('Cancel remote schedule')).toBeInTheDocument();
  rerender(<PublishingScreen {...props} data={{publications:[{...publication,status:'cancelled'}]}}/>);
  expect(screen.queryByText('Cancel remote schedule')).not.toBeInTheDocument();
  rerender(<PublishingScreen {...props} selected={{id:'other',revision:1,variants:[]}} data={{publications:[publication]}}/>);
  expect(screen.queryByText('Publication pub')).not.toBeInTheDocument();
});
