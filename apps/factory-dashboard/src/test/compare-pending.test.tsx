import React from 'react';
import {render, screen} from '@testing-library/react';
import {it, expect} from 'vitest';
import {CompareScreen} from '../features/compare/CompareScreen';

it('keeps the reference playable without implying pending finals are rendering', () => {
  render(<CompareScreen entries={[
    {key:'source', label:'Reference', media_url:'/source.mp4'},
    {key:'A', label:'A · pending', pending:true},
    {key:'B', label:'B · pending', pending:true, state:'stale'},
  ]}/>);
  expect(screen.getByLabelText('Reference playback')).toHaveAttribute('src','/source.mp4');
  expect(screen.getAllByText('Not ready')).toHaveLength(2);
  expect(screen.queryByText(/Rendering/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText('A · pending playback')).not.toBeInTheDocument();
  expect(screen.getByLabelText('B validation state')).toHaveTextContent('stale');
});
