import "./App.css";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import StoryLoader from "./components/StoryLoader";
import StoryGenerator from "./components/StoryGenerator.jsx";

function App() {
  return (
    <Router>
      <div className="app-container">
        <header>
          <h1 className="loading-title">The Adventure</h1>
          <p className="loading-info">AI-Powered Interactive Journeys</p>
        </header>
        
        <main>
          <Routes>
            {/* The main input screen */}
            <Route path="/" element={<StoryGenerator />} />
            
            {/* The dynamic story viewing screen */}
            <Route path="/story/:id" element={<StoryLoader />} />
          </Routes>
        </main>

        <footer>
          <p>© 2026 The Adventure — Built with FastAPI & React</p>
        </footer>
      </div>
    </Router>
  );
}

export default App;