import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import AppShell from './components/AppShell'
import Dashboard from './pages/Dashboard'
import Agents from './pages/Agents'
import Teams from './pages/Teams'
import RunStudio from './pages/RunStudio'
import Runs from './pages/Runs'
import Settings from './pages/Settings'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path='/' element={<Dashboard/>}/>
          <Route path='/agents' element={<Agents/>}/>
          <Route path='/teams' element={<Teams/>}/>
          <Route path='/studio' element={<RunStudio/>}/>
          <Route path='/runs' element={<Runs/>}/>
          <Route path='/settings' element={<Settings/>}/>
        </Routes>
      </AppShell>
    </BrowserRouter>
  </React.StrictMode>
)
