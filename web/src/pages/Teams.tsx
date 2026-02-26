import { useState } from 'react';import YamlEditor from '../components/YamlEditor';
export default function Teams(){const [yaml,setYaml]=useState('name: NewTeam\nmode: sequential\nagents: []');return <div><h2>Teams</h2><YamlEditor value={yaml} onChange={setYaml}/></div>}
