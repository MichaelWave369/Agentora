import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import AppShell from './components/AppShell'
import Dashboard from './pages/Dashboard'
import Agents from './pages/Agents'
import Teams from './pages/Teams'
import Marketplace from './pages/Marketplace'
import RunStudio from './pages/RunStudio'
import Runs from './pages/Runs'
import Analytics from './pages/Analytics'
import Settings from './pages/Settings'
import StudioMode from './pages/StudioMode'
import BandMode from './pages/BandMode'
import ArenaMode from './pages/ArenaMode'
import GatheringMode from './pages/GatheringMode'
import LegacyMode from './pages/LegacyMode'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path='/' element={<Dashboard/>}/>
          <Route path='/studio-mode' element={<StudioMode/>}/>
          <Route path='/band-mode' element={<BandMode/>}/>
          <Route path='/arena-mode' element={<ArenaMode/>}/>
          <Route path='/gathering-mode' element={<GatheringMode/>}/>
          <Route path='/legacy-mode' element={<LegacyMode/>}/>
          <Route path='/agents' element={<Agents/>}/>
          <Route path='/teams' element={<Teams/>}/>
          <Route path='/marketplace' element={<Marketplace/>}/>
          <Route path='/studio' element={<RunStudio/>}/>
          <Route path='/runs' element={<Runs/>}/>
          <Route path='/analytics' element={<Analytics/>}/>
          <Route path='/settings' element={<Settings/>}/>
        </Routes>
      </AppShell>
    </BrowserRouter>
  </React.StrictMode>
)
