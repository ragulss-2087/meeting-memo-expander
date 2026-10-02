import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  LayoutDashboard,
  FileText,
  ListTodo,
  Search,
  Brain,
  Upload,
  Download,
  CheckCircle2,
  Mic,
  MicOff,
  Volume2,
  MessageCircle
} from "lucide-react";
import "./styles.css";

const API =
  import.meta.env.VITE_API_URL ||
  "https://meeting-memo-backend-v2.onrender.com/api";


// ======================================================
// API HELPER
// ======================================================

async function api(path, opts = {}) {
  const response = await fetch(API + path, opts);

  if (!response.ok) {
    let message = "Something went wrong.";

    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      message = await response.text();
    }

    if (response.status === 429) {
      message =
        "Gemini quota reached. Please try again after the quota resets.";
    }

    throw new Error(message);
  }

  return response.json();
}


// ======================================================
// APP
// ======================================================

function App() {

  // ----------------------------------------------------
  // PROJECTS
  // ----------------------------------------------------

  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(null);

  // ----------------------------------------------------
  // MEETINGS
  // ----------------------------------------------------

  const [meetings, setMeetings] = useState([]);
  const [selected, setSelected] = useState(null);

  // ----------------------------------------------------
  // NEW MEETING
  // ----------------------------------------------------

  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");

  // ----------------------------------------------------
  // GENERAL STATE
  // ----------------------------------------------------

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ----------------------------------------------------
  // TASKS / DECISIONS
  // ----------------------------------------------------

  const [tasks, setTasks] = useState([]);
  const [decisions, setDecisions] = useState([]);

  // ----------------------------------------------------
  // SEARCH
  // ----------------------------------------------------

  const [search, setSearch] = useState("");
  const [results, setResults] = useState(null);

  // ----------------------------------------------------
  // NAVIGATION
  // ----------------------------------------------------

  const [view, setView] = useState("dashboard");

  // ====================================================
  // VOICE AGENT STATE
  // ====================================================

  const [voiceActive, setVoiceActive] = useState(false);

  const [voiceStatus, setVoiceStatus] =
    useState("idle");

  const [conversation, setConversation] =
    useState([]);

  const recognitionRef =
    useRef(null);

  const shouldContinueListening =
    useRef(false);

  const speakingRef =
    useRef(false);

  const processingRef =
    useRef(false);

  const conversationRef =
    useRef([]);

  const currentAIAnswerRef =
    useRef("");

  const restartingRecognitionRef =
    useRef(false);


  // ====================================================
  // LOAD DATA
  // ====================================================

  async function load() {

  try {

    setError("");

    const projectsData =
      await api("/projects");

    setProjects(projectsData);

    const firstProject =
      projectsData[0];

    setProject(firstProject);

    if (!firstProject) {

      setMeetings([]);
      setTasks([]);
      setDecisions([]);

      return;
    }

    const meetingData =
      await api(
        "/meetings?project_id=" +
        firstProject.id
      );

    setMeetings(meetingData);


    // ==================================================
    // LOAD TASKS AND DECISIONS FOR ALL MEETINGS
    // ==================================================

    const taskResults =
      await Promise.all(
        meetingData.map(
          meeting =>
            api(
              `/meetings/${meeting.id}/tasks`
            )
        )
      );

    const decisionResults =
      await Promise.all(
        meetingData.map(
          meeting =>
            api(
              `/meetings/${meeting.id}/decisions`
            )
        )
      );


    // Flatten all meeting results
    const allTasks =
      taskResults.flat();

    const allDecisions =
      decisionResults.flat();


    setTasks(allTasks);
    setDecisions(allDecisions);

  } catch (e) {

    setError(e.message);

  }
}


  useEffect(() => {

    load();

  }, []);


  // ====================================================
  // SELECT MEETING
  // ====================================================

  async function selectMeeting(id) {

    stopVoiceConversation();

    try {

      setError("");

      setConversation([]);

      conversationRef.current = [];

      const meeting =
        await api(
          "/meetings/" + id
        );

      let analysis = null;

      if (meeting.analysis_json) {

        try {

          analysis =
            typeof meeting.analysis_json ===
            "string"
              ? JSON.parse(
                  meeting.analysis_json
                )
              : meeting.analysis_json;

        } catch {

          analysis = null;
        }
      }

      setSelected({
        ...meeting,
        analysis
      });

      setView("meetings");

    } catch (e) {

      setError(e.message);
    }
  }


  // ====================================================
  // CREATE MEETING
  // ====================================================

  async function createMeeting() {

    if (
      !project ||
      !title.trim() ||
      !transcript.trim()
    ) {

      setError(
        "Please select a project, enter a meeting title, and provide meeting content."
      );

      return;
    }

    setLoading(true);
    setError("");

    try {

      const created =
        await api("/meetings", {

          method: "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          body: JSON.stringify({

            project_id:
              project.id,

            title:
              title,

            transcript:
              transcript

          })
        });

      setTitle("");
      setTranscript("");

      await load();

      await selectMeeting(
        created.id
      );

    } catch (e) {

      setError(e.message);

    } finally {

      setLoading(false);
    }
  }


  // ====================================================
  // DELETE MEETING
  // ====================================================

  async function deleteMeeting(id) {

    const meeting =
      meetings.find(
        item => item.id === id
      );

    const confirmed =
      window.confirm(
        `Delete "${meeting?.title || "this meeting"}"?\n\nThis will also delete its tasks and decisions.`
      );

    if (!confirmed) {
      return;
    }

    try {

      setError("");

      stopVoiceConversation();

      await api(
        `/meetings/${id}`,
        {
          method: "DELETE"
        }
      );

      // If the deleted meeting is currently open,
      // close it.
      if (
        selected?.id === id
      ) {

        setSelected(null);

        setConversation([]);

        conversationRef.current = [];
      }

      // Reload meetings, tasks and decisions.
      await load();

      setView("meetings");

    } catch (e) {

      setError(e.message);
    }
  }


  // ====================================================
  // AUDIO FILE UPLOAD
  // ====================================================

  async function uploadAudio(event) {

    const file =
      event.target.files[0];

    if (!file) {
      return;
    }

    const formData =
      new FormData();

    formData.append(
      "file",
      file
    );

    setLoading(true);
    setError("");

    try {

      const data =
        await api(
          "/transcribe",
          {
            method: "POST",
            body: formData
          }
        );

      setTranscript(
        data.text || ""
      );

    } catch (e) {

      setError(e.message);

    } finally {

      setLoading(false);
    }
  }


  // ====================================================
  // SEARCH
  // ====================================================

  async function doSearch() {

    if (!search.trim()) {
      return;
    }

    try {

      setError("");

      const data =
        await api(
          "/search?q=" +
          encodeURIComponent(
            search
          )
        );

      setResults(data);

    } catch (e) {

      setError(e.message);
    }
  }


  // ====================================================
  // SPEECH RECOGNITION SUPPORT
  // ====================================================

  function getSpeechRecognition() {

    return (
      window.SpeechRecognition ||
      window.webkitSpeechRecognition ||
      null
    );
  }


  // ====================================================
  // STOP RECOGNITION
  // ====================================================

  function stopRecognition() {

    if (recognitionRef.current) {

      try {

        recognitionRef.current.onend = null;

        recognitionRef.current.onerror = null;

        recognitionRef.current.stop();

      } catch {
        // Already stopped.
      }

      recognitionRef.current = null;
    }
  }


  // ====================================================
  // TEXT NORMALIZATION
  // ====================================================

  function normalizeSpeech(text) {

    return (text || "")
      .toLowerCase()
      .replace(
        /[^a-z0-9\s]/g,
        " "
      )
      .replace(
        /\s+/g,
        " "
      )
      .trim();
  }


  // ====================================================
  // CHECK WHETHER RECOGNIZED SPEECH IS AI VOICE
  // ====================================================

  function looksLikeCurrentAIAnswer(text) {

    const heard =
      normalizeSpeech(text);

    const answer =
      normalizeSpeech(
        currentAIAnswerRef.current
      );

    if (!heard || !answer) {
      return false;
    }

    if (
      answer.includes(heard) &&
      heard.length >= 12
    ) {
      return true;
    }

    if (
      heard.includes(answer) &&
      answer.length >= 12
    ) {
      return true;
    }

    const heardWords =
      heard.split(" ");

    const answerWords =
      answer.split(" ");

    if (
      heardWords.length < 4 ||
      answerWords.length < 4
    ) {
      return false;
    }

    let matching = 0;

    for (
      const word of heardWords
    ) {

      if (
        answerWords.includes(word)
      ) {

        matching += 1;
      }
    }

    return (
      matching /
      heardWords.length >=
      0.75
    );
  }


  // ====================================================
  // TEXT TO SPEECH
  // ====================================================

  function cancelAISpeech() {

    if (
      window.speechSynthesis
    ) {

      window.speechSynthesis.cancel();
    }

    speakingRef.current =
      false;

    currentAIAnswerRef.current =
      "";
  }


  function speakAIAnswer(text) {

    return new Promise(
      resolve => {

        if (
          !window.speechSynthesis
        ) {

          speakingRef.current =
            false;

          resolve();

          return;
        }

        speakingRef.current =
          true;

        currentAIAnswerRef.current =
          text;

        setVoiceStatus(
          "speaking"
        );

        window.speechSynthesis.cancel();

        const utterance =
          new SpeechSynthesisUtterance(
            text
          );

        utterance.lang =
          "en-IN";

        utterance.rate =
          1;

        utterance.pitch =
          1;

        utterance.volume =
          1;

        utterance.onend =
          () => {

            speakingRef.current =
              false;

            currentAIAnswerRef.current =
              "";

            resolve();
          };

        utterance.onerror =
          () => {

            speakingRef.current =
              false;

            currentAIAnswerRef.current =
              "";

            resolve();
          };

        window.speechSynthesis.speak(
          utterance
        );
      }
    );
  }


  // ====================================================
  // SEND QUESTION TO GEMINI
  // ====================================================

  async function sendVoiceQuestion(
    question
  ) {

    if (
      !selected ||
      !question.trim() ||
      processingRef.current
    ) {

      return;
    }

    processingRef.current =
      true;

    stopRecognition();

    cancelAISpeech();

    const cleanQuestion =
      question.trim();

    try {

      setVoiceStatus(
        "thinking"
      );

      const history =
        conversationRef.current
          .slice(-8)
          .map(
            message => ({
              role:
                message.role,

              text:
                message.text
            })
          );

      setConversation(
        previous => {

          const next = [
            ...previous,
            {
              role: "user",
              text: cleanQuestion
            }
          ];

          conversationRef.current =
            next;

          return next;
        }
      );

      const data =
        await api(
          `/meetings/${selected.id}/ask`,
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json"
            },

            body:
              JSON.stringify({
                question:
                  cleanQuestion,

                history
              })
          }
        );

      const answer =
        data.answer?.answer ||
        data.answer ||
        "I could not find an answer in this meeting.";

      setConversation(
        previous => {

          const next = [
            ...previous,
            {
              role: "ai",
              text: answer
            }
          ];

          conversationRef.current =
            next;

          return next;
        }
      );

      startListening();

      await speakAIAnswer(
        answer
      );

    } catch (e) {

      setError(
        e.message
      );

      setVoiceStatus(
        "error"
      );

      shouldContinueListening.current =
        false;

    } finally {

      processingRef.current =
        false;

      currentAIAnswerRef.current =
        "";

      if (
        shouldContinueListening.current
      ) {

        startListening();
      }
    }
  }


  // ====================================================
  // START LISTENING
  // ====================================================

  function startListening() {

    if (
      !shouldContinueListening.current
    ) {

      return;
    }

    const SpeechRecognition =
      getSpeechRecognition();

    if (!SpeechRecognition) {

      setError(
        "Live voice recognition is not supported in this browser. Please use Google Chrome."
      );

      shouldContinueListening.current =
        false;

      setVoiceActive(
        false
      );

      return;
    }

    if (
      recognitionRef.current ||
      restartingRecognitionRef.current
    ) {

      return;
    }

    const recognition =
      new SpeechRecognition();

    recognition.continuous =
      true;

    recognition.interimResults =
      true;

    recognition.lang =
      "en-IN";

    recognition.maxAlternatives =
      1;

    recognition.onstart =
      () => {

        setVoiceActive(
          true
        );

        if (
          !speakingRef.current &&
          !processingRef.current
        ) {

          setVoiceStatus(
            "listening"
          );
        }
      };

    recognition.onresult =
      event => {

        let finalText =
          "";

        let interimText =
          "";

        for (
          let i =
            event.resultIndex;

          i <
          event.results.length;

          i += 1
        ) {

          const text =
            event.results[i][0]
              ?.transcript ||
            "";

          if (
            event.results[i]
              .isFinal
          ) {

            finalText +=
              " " + text;

          } else {

            interimText +=
              " " + text;
          }
        }

        finalText =
          finalText.trim();

        interimText =
          interimText.trim();

        if (
          speakingRef.current
        ) {

          const candidate =
            finalText ||
            interimText;

          if (
            candidate &&
            !looksLikeCurrentAIAnswer(
              candidate
            )
          ) {

            if (
              finalText
            ) {

              cancelAISpeech();

              stopRecognition();

              sendVoiceQuestion(
                finalText
              );
            }
          }

          return;
        }

        if (
          processingRef.current
        ) {

          return;
        }

        if (
          finalText
        ) {

          stopRecognition();

          sendVoiceQuestion(
            finalText
          );
        }
      };

    recognition.onerror =
      event => {

        console.log(
          "Speech recognition error:",
          event.error
        );

        if (
          event.error ===
          "not-allowed"
        ) {

          setError(
            "Microphone permission was denied. Please allow microphone access in Chrome."
          );

          shouldContinueListening.current =
            false;

          setVoiceActive(
            false
          );

          setVoiceStatus(
            "error"
          );

          return;
        }

        if (
          event.error ===
            "aborted" ||
          event.error ===
            "no-speech"
        ) {

          return;
        }

        if (
          shouldContinueListening.current
        ) {

          setTimeout(
            () =>
              startListening(),
            400
          );
        }
      };

    recognition.onend =
      () => {

        if (
          recognitionRef.current ===
          recognition
        ) {

          recognitionRef.current =
            null;
        }

        if (
          shouldContinueListening.current &&
          !restartingRecognitionRef.current
        ) {

          restartingRecognitionRef.current =
            true;

          setTimeout(
            () => {

              restartingRecognitionRef.current =
                false;

              startListening();

            },
            250
          );
        }
      };

    recognitionRef.current =
      recognition;

    try {

      recognition.start();

    } catch (e) {

      recognitionRef.current =
        null;

      console.log(
        "Could not start recognition:",
        e
      );
    }
  }


  // ====================================================
  // START VOICE CONVERSATION
  // ====================================================

  function startVoiceConversation() {

    if (!selected) {

      setError(
        "Please open a meeting first."
      );

      return;
    }

    if (
      !getSpeechRecognition()
    ) {

      setError(
        "Live voice conversation requires Google Chrome."
      );

      return;
    }

    setError("");

    processingRef.current =
      false;

    setConversation([]);

    conversationRef.current =
      [];

    shouldContinueListening.current =
      true;

    setVoiceActive(
      true
    );

    setVoiceStatus(
      "listening"
    );

    startListening();
  }


  // ====================================================
  // STOP VOICE CONVERSATION
  // ====================================================

  function stopVoiceConversation() {

    shouldContinueListening.current =
      false;

    processingRef.current =
      false;

    stopRecognition();

    cancelAISpeech();

    speakingRef.current =
      false;

    processingRef.current =
      false;

    setVoiceActive(
      false
    );

    setVoiceStatus(
      "idle"
    );
  }


  // ====================================================
  // CLEANUP
  // ====================================================

  useEffect(() => {

    return () => {

      shouldContinueListening.current =
        false;

      stopRecognition();

      if (
        window.speechSynthesis
      ) {

        window.speechSynthesis.cancel();
      }
    };

  }, []);


  // ====================================================
  // ANALYSIS
  // ====================================================

  const analysis =
    selected?.analysis ||
    null;


  // ====================================================
  // UI
  // ====================================================

  return (

    <div className="app">

      {/* ==================================================
          SIDEBAR
      =================================================== */}

      <aside>

        <div className="brand">

          <Brain />

          Memo<span>Agent</span>

        </div>


        <nav>

          <button
            className={
              view === "dashboard"
                ? "active"
                : ""
            }
            onClick={() => {

              stopVoiceConversation();

              setView(
                "dashboard"
              );

              setSelected(null);
            }}
          >

            <LayoutDashboard />

            Dashboard

          </button>


          <button
            className={
              view === "meetings"
                ? "active"
                : ""
            }
            onClick={() => {

              stopVoiceConversation();

              setView(
                "meetings"
              );

              setSelected(null);
            }}
          >

            <FileText />

            Meetings

          </button>


          <button
            className={
              view === "tasks"
                ? "active"
                : ""
            }
            onClick={() => {

              stopVoiceConversation();

              setView(
                "tasks"
              );

              setSelected(null);
            }}
          >

            <ListTodo />

            Tasks

          </button>


          <button
            className={
              view === "decisions"
                ? "active"
                : ""
            }
            onClick={() => {

              stopVoiceConversation();

              setView(
                "decisions"
              );

              setSelected(null);
            }}
          >

            <CheckCircle2 />

            Decisions

          </button>

        </nav>


        {/* PROJECT */}

        <div className="sidebox">

          <small>
            PROJECT
          </small>

          <select
            value={
              project?.id || ""
            }
            onChange={
              async event => {

                const newProject =
                  projects.find(
                    item =>
                      item.id ==
                      event.target.value
                  );

                setProject(
                  newProject
                );

                if (
                  newProject
                ) {

                  try {

                    const data =
                      await api(
                        "/meetings?project_id=" +
                        newProject.id
                      );

                    setMeetings(
                      data
                    );

                  } catch (
                    err
                  ) {

                    setError(
                      err.message
                    );
                  }
                }
              }
            }
          >

            {projects.map(
              item => (

                <option
                  key={
                    item.id
                  }
                  value={
                    item.id
                  }
                >

                  {item.name}

                </option>

              )
            )}

          </select>

        </div>

      </aside>


      {/* ==================================================
          MAIN
      =================================================== */}

      <main>

        {/* HEADER */}

        <header>

          <div>

            <h1>

              {view ===
                "dashboard" &&
                "Meeting Intelligence"}

              {view ===
                "meetings" &&
                "Meetings"}

              {view ===
                "tasks" &&
                "Tasks"}

              {view ===
                "decisions" &&
                "Decisions"}

            </h1>

            <p>
              Turn any meeting into
              searchable knowledge, decisions,
              action items, and accountable work.
            </p>

          </div>


          {/* SEARCH */}

          <div className="search">

            <Search
              size={18}
            />

            <input
              placeholder="Search meetings or tasks..."
              value={search}
              onChange={
                event =>
                  setSearch(
                    event.target.value
                  )
              }
              onKeyDown={
                event => {

                  if (
                    event.key ===
                    "Enter"
                  ) {

                    doSearch();
                  }
                }
              }
            />

          </div>

        </header>


        {/* ERROR */}

        {error && (

          <div className="error">

            {error}

          </div>

        )}


        {/* SEARCH RESULTS */}

        {results && (

          <section className="results">

            <h3>
              Search results
            </h3>

            {results.meetings.map(
              meeting => (

                <button
                  key={
                    meeting.id
                  }
                  onClick={() =>
                    selectMeeting(
                      meeting.id
                    )
                  }
                >

                  {meeting.title}

                </button>

              )
            )}


            {results.tasks.map(
              task => (

                <div
                  key={
                    "task-" +
                    task.id
                  }
                >

                  {task.title}

                  {" — "}

                  {task.owner ||
                    "Unassigned"}

                </div>

              )
            )}

          </section>

        )}


        {/* ==================================================
            DASHBOARD
        =================================================== */}

        {view ===
          "dashboard" && (

          <>

            <section className="grid">

              {/* NEW MEETING */}

              <div className="card composer">

                <div className="cardhead">

                  <div>

                    <h2>
                      New meeting
                    </h2>

                    <span>
                      Capture any meeting from any
                      industry using a transcript or
                      audio recording.
                    </span>

                  </div>


                  <label
                    className="upload"
                  >

                    <Upload
                      size={16}
                    />

                    Audio

                    <input
                      type="file"
                      accept="audio/*"
                      onChange={
                        uploadAudio
                      }
                    />

                  </label>

                </div>


                <input
                  className="input"
                  placeholder="Meeting title"
                  value={title}
                  onChange={
                    event =>
                      setTitle(
                        event.target.value
                      )
                  }
                />


                <textarea
                  placeholder="Paste meeting transcript here..."
                  value={transcript}
                  onChange={
                    event =>
                      setTranscript(
                        event.target.value
                      )
                  }
                />


                <button
                  className="primary"
                  disabled={
                    loading
                  }
                  onClick={
                    createMeeting
                  }
                >

                  {loading
                    ? "Processing…"
                    : "Analyze meeting"}

                </button>

              </div>


              {/* STATS */}

              <div className="card stats">

                <h2>
                  Workspace
                </h2>


                <div className="stat">

                  <b>
                    {
                      meetings.length
                    }
                  </b>

                  <span>
                    Meetings
                  </span>

                </div>


                <div className="stat">

                  <b>
                    {
                      tasks.filter(
                        task =>
                          task.status !==
                          "Completed"
                      ).length
                    }
                  </b>

                  <span>
                    Open tasks
                  </span>

                </div>


                <div className="stat">

                  <b>
                    {
                      decisions.length
                    }
                  </b>

                  <span>
                    Decisions
                  </span>

                </div>

              </div>

            </section>


            {/* RECENT MEETINGS */}

            <section className="card">

              <div className="cardhead">

                <div>

                  <h2>
                    Recent meetings
                  </h2>

                  <span>
                    Select a meeting to
                    inspect its memory.
                  </span>

                </div>

              </div>


              {meetings.length === 0 ? (

                <p>
                  No meetings found.
                </p>

              ) : (

                meetings.map(
                  meeting => (

                    <div
                      className="meetingrow"
                      key={
                        meeting.id
                      }
                      onClick={() =>
                        selectMeeting(
                          meeting.id
                        )
                      }
                    >

                      <FileText
                        size={18}
                      />

                      <span>
                        {
                          meeting.title
                        }
                      </span>

                      <small>
                        {
                          new Date(
                            meeting.created_at
                          ).toLocaleString()
                        }
                      </small>


                      {/* DELETE BUTTON */}

                      <button
                        type="button"
                        className="delete-meeting"
                        onClick={
                          event => {

                            event.stopPropagation();

                            deleteMeeting(
                              meeting.id
                            );
                          }
                        }
                        title="Delete meeting"
                      >

                        Delete

                      </button>

                    </div>

                  )
                )

              )}

            </section>

          </>
        )}


        {/* ==================================================
            MEETINGS
        =================================================== */}

        {view ===
          "meetings" && (

          <>

            {/* MEETING LIST */}

            {!selected && (

              <section className="card">

                <div className="cardhead">

                  <div>

                    <h2>
                      All meetings
                    </h2>

                    <span>
                      Select a meeting to
                      talk with its AI.
                    </span>

                  </div>

                </div>


                {meetings.length === 0 ? (

                  <p>
                    No meetings found.
                  </p>

                ) : (

                  meetings.map(
                    meeting => (

                      <div
                        className="meetingrow"
                        key={
                          meeting.id
                        }
                        onClick={() =>
                          selectMeeting(
                            meeting.id
                          )
                        }
                      >

                        <FileText
                          size={18}
                        />

                        <span>
                          {
                            meeting.title
                          }
                        </span>

                        <small>
                          {
                            new Date(
                              meeting.created_at
                            ).toLocaleString()
                          }
                        </small>


                        {/* DELETE BUTTON */}

                        <button
                          type="button"
                          className="delete-meeting"
                          onClick={
                            event => {

                              event.stopPropagation();

                              deleteMeeting(
                                meeting.id
                              );
                            }
                          }
                          title="Delete meeting"
                        >

                          Delete

                        </button>

                      </div>

                    )
                  )

                )}

              </section>

            )}


            {/* SELECTED MEETING */}

            {selected && (

              <section className="card analysis">

                {/* MEETING HEADER */}

                <div className="cardhead">

                  <div>

                    <h2>
                      {
                        selected.title
                      }
                    </h2>

                    <span>
                      Meeting analysis
                    </span>

                  </div>


                  <div className="actions">

                    <a
                      href={
                        `${API}/meetings/${selected.id}/export/docx`
                      }
                    >

                      <Download
                        size={15}
                      />

                      DOCX

                    </a>


                    <a
                      href={
                        `${API}/meetings/${selected.id}/export/pdf`
                      }
                    >

                      <Download
                        size={15}
                      />

                      PDF

                    </a>


                    {/* DELETE OPEN MEETING */}

                    <button
                      type="button"
                      className="delete-meeting"
                      onClick={() =>
                        deleteMeeting(
                          selected.id
                        )
                      }
                      title="Delete meeting"
                    >

                      Delete Meeting

                    </button>

                  </div>

                </div>


                {analysis ? (

                  <>

                    {/* SUMMARY */}

                    <div className="summary">

                      {
                        analysis.summary ||
                        "No summary available."
                      }

                    </div>


                    {/* DISCUSSION / ISSUES / RISKS */}

                    <div className="cols">

                      <Panel
                        title="Discussion points"
                        items={
                          analysis.discussion_points ||
                          []
                        }
                      />


                      <Panel
                        title="Unresolved issues"
                        items={
                          analysis.unresolved_issues ||
                          []
                        }
                      />


                      <Panel
                        title="Risks"
                        items={
                          analysis.risks ||
                          []
                        }
                      />

                    </div>


                    {/* DECISIONS / TASKS */}

                    <div className="cols">

                      <Panel
                        title="Decisions"
                        items={
                          (
                            analysis.decisions ||
                            []
                          ).map(
                            item =>
                              typeof item ===
                              "string"
                                ? item
                                : item.decision
                          )
                        }
                      />


                      <div>

                        <h3>
                          Action items
                        </h3>


                        {(
                          analysis.action_items ||
                          []
                        ).map(
                          (
                            item,
                            index
                          ) => {

                            const task =
                              typeof item ===
                              "string"
                                ? {
                                    title:
                                      item,
                                    owner:
                                      "",
                                    deadline:
                                      ""
                                  }
                                : item;

                            return (

                              <div
                                className="task"
                                key={
                                  index
                                }
                              >

                                <b>
                                  {
                                    task.title
                                  }
                                </b>

                                <span>

                                  {
                                    task.owner ||
                                    "Owner unknown"
                                  }

                                  {" · "}

                                  {
                                    task.deadline ||
                                    "No deadline"
                                  }

                                </span>

                              </div>

                            );
                          }
                        )}

                      </div>

                    </div>


                    {/* =================================================
                        LIVE VOICE MEETING AGENT
                    ================================================== */}

                    <div
                      className="voice-agent"
                    >

                      <div className="voice-agent-header">

                        <div>

                          <h2>
                            <MessageCircle
                              size={22}
                            />

                            Meeting AI
                          </h2>

                          <p>
                            Have a live voice
                            conversation about
                            this meeting.
                          </p>

                        </div>

                      </div>


                      {/* VOICE CIRCLE */}

                      <div
                        className={
                          "voice-orb " +
                          voiceStatus
                        }
                      >

                        {voiceStatus ===
                          "speaking" ? (

                          <Volume2
                            size={42}
                          />

                        ) : voiceActive ? (

                          <Mic
                            size={42}
                          />

                        ) : (

                          <Mic
                            size={42}
                          />

                        )}

                      </div>


                      {/* STATUS */}

                      <div
                        className="voice-status"
                      >

                        {voiceStatus ===
                          "idle" && (
                          <>
                            Ready to talk
                          </>
                        )}

                        {voiceStatus ===
                          "listening" && (
                          <>
                            Listening...
                          </>
                        )}

                        {voiceStatus ===
                          "thinking" && (
                          <>
                            Thinking...
                          </>
                        )}

                        {voiceStatus ===
                          "speaking" && (
                          <>
                            AI is speaking...
                          </>
                        )}

                        {voiceStatus ===
                          "error" && (
                          <>
                            Voice error
                          </>
                        )}

                      </div>


                      {/* START / STOP */}

                      {!voiceActive ? (

                        <button
                          className="voice-button"
                          onClick={
                            startVoiceConversation
                          }
                        >

                          <Mic
                            size={20}
                          />

                          Start Voice
                          Conversation

                        </button>

                      ) : (

                        <button
                          className="voice-button stop"
                          onClick={
                            stopVoiceConversation
                          }
                        >

                          <MicOff
                            size={20}
                          />

                          Stop Conversation

                        </button>

                      )}


                      {/* CONVERSATION */}

                      {conversation.length >
                        0 && (

                        <div
                          className="conversation"
                        >

                          {conversation.map(
                            (
                              message,
                              index
                            ) => (

                              <div
                                className={
                                  message.role ===
                                  "user"
                                    ? "voice-message user-message"
                                    : "voice-message ai-message"
                                }
                                key={
                                  index
                                }
                              >

                                <strong>

                                  {message.role ===
                                  "user"
                                    ? "You"
                                    : "AI"}

                                </strong>


                                <div>

                                  {
                                    message.text
                                  }

                                </div>

                              </div>

                            )
                          )}

                        </div>

                      )}

                    </div>

                  </>

                ) : (

                  <div className="summary">

                    This meeting does not
                    have analysis data
                    available yet.

                  </div>

                )}

              </section>

            )}

          </>
        )}


        {/* ==================================================
            TASKS
        =================================================== */}

        {view ===
          "tasks" && (

          <section className="card">

            <div className="cardhead">

              <div>

                <h2>
                  All tasks
                </h2>

                <span>
                  Tasks extracted from
                  meetings.
                </span>

              </div>

            </div>


            {tasks.length ===
            0 ? (

              <p>
                No tasks found.
              </p>

            ) : (

              tasks.map(
                task => (

                  <div
                    className="task"
                    key={
                      task.id
                    }
                  >

                    <b>
                      {
                        task.title
                      }
                    </b>

                    <span>

                      {
                        task.owner ||
                        "Owner unknown"
                      }

                      {" · "}

                      {
                        task.deadline ||
                        "No deadline"
                      }

                      {" · "}

                      {
                        task.status
                      }

                    </span>

                  </div>

                )
              )

            )}

          </section>

        )}


        {/* ==================================================
            DECISIONS
        ==================================================== */}

        {view ===
          "decisions" && (

          <section className="card">

            <div className="cardhead">

              <div>

                <h2>
                  All decisions
                </h2>

                <span>
                  Decisions recorded from
                  meetings.
                </span>

              </div>

            </div>


            {decisions.length ===
            0 ? (

              <p>
                No decisions found.
              </p>

            ) : (

              decisions.map(
                decision => (

                  <div
                    className="task"
                    key={
                      decision.id
                    }
                  >

                    <b>
                      {
                        decision.decision
                      }
                    </b>

                    <span>
                      {
                        decision.meeting_title
                      }
                    </span>

                  </div>

                )
              )

            )}

          </section>

        )}

      </main>

    </div>
  );
}


// ======================================================
// PANEL COMPONENT
// ======================================================

function Panel({
  title,
  items = []
}) {

  return (

    <div>

      <h3>
        {title}
      </h3>

      <ul>

        {items.map(
          (
            item,
            index
          ) => (

            <li
              key={index}
            >

              {
                typeof item ===
                "string"
                  ? item
                  : String(item)
              }

            </li>

          )
        )}

      </ul>

    </div>
  );
}


// ======================================================
// START REACT
// ======================================================

createRoot(
  document.getElementById("root")
).render(
  <App />
);