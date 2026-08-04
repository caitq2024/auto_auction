import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import HarnessApp from './HarnessApp'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HarnessApp />
  </StrictMode>,
)
