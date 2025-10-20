// Q&A Intake page logic
(function(){
  const synth = window.speechSynthesis;
  let availableVoices = [];

  function loadVoices() {
    try { availableVoices = synth.getVoices() || []; } catch { availableVoices = []; }
  }

  function setVitalsStatus(text) {
    try {
      const el = document.getElementById('vitalsStatusText');
      if (el) el.textContent = text;
    } catch {}
  }
  loadVoices();
  if (typeof speechSynthesis !== 'undefined' && 'onvoiceschanged' in speechSynthesis) {
    speechSynthesis.onvoiceschanged = loadVoices;
  }

  let recog = null;
  if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
    recog = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recog.lang = 'en-US';
    recog.interimResults = false;
    recog.maxAlternatives = 1;
    try { window.recog = recog; } catch {}
  }

  function pickVoiceForLang(targetLang) {
    if (!availableVoices || availableVoices.length === 0) return null;
    const exact = availableVoices.find(v => (v.lang || '').toLowerCase() === targetLang.toLowerCase());
    if (exact) return exact;
    const starts = availableVoices.find(v => (v.lang || '').toLowerCase().startsWith(targetLang.split('-')[0].toLowerCase()));
    return starts || null;
  }

  const questions_en = [
    { prompt: "Hi there, I'm here to help you feel better. Please scan your QR code in front of my camera.", field: "qrScan", type: "qr_scan" },
    { prompt: "I'm really sorry you're not feeling well. Could you tell me what's been bothering you the most today?", field: "chiefComplaint" },
    { prompt: "That sounds uncomfortable. Can you describe how the pain feels — maybe sharp, dull, burning, or something else?", field: "painDescription" },
    { prompt: "Thank you for sharing that. Have you noticed anything else that's been bothering you or any changes in how you feel lately?", field: "additionalFeelings" },
    { prompt: "Before we continue, do you have any health conditions — now or in the past — that you'd like me to know about?", field: "medicalHistory" }
  ];

  const questions_hi = [
    { prompt: "नमस्ते, मैं आपकी मदद के लिए यहाँ हूँ। कृपया अपना QR कोड मेरे कैमरे के सामने स्कैन करें।", field: "qrScan", type: "qr_scan" },
    { prompt: "मुझे खेद है कि आप ठीक नहीं लग रहे। क्या आप बता सकते हैं कि आज आपको सबसे ज्यादा क्या परेशान कर रहा है?", field: "chiefComplaint" },
    { prompt: "यह असहज लगता है। क्या आप बता सकते हैं कि दर्द कैसा लगता है - तेज, सुस्त, जलन या कुछ और?", field: "painDescription" },
    { prompt: "यह साझा करने के लिए धन्यवाद। क्या आपने कुछ और नोटिस किया है जो आपको परेशान कर रहा है या आपके महसूस करने के तरीके में कोई बदलाव?", field: "additionalFeelings" },
    { prompt: "आगे बढ़ने से पहले, क्या आपके पास कोई स्वास्थ्य स्थिति है - अभी या अतीत में - जो आप मुझे बताना चाहेंगे?", field: "medicalHistory" }
  ];

  function getActiveQuestions() {
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    return (lang === 'hi') ? questions_hi : questions_en;
  }

  function setDisplayIfExists(elementId, text) {
    const el = document.getElementById(elementId);
    if (el) el.innerText = text;
  }

  function speakChunked(text, callback) {
    const chunks = text.match(/[^.!?]+[.!?]*/g) || [text];
    let i = 0;
    (function next(){
      if (i < chunks.length) {
        const utter = new SpeechSynthesisUtterance(chunks[i].trim());
        const lang = (sessionStorage.getItem('qa_lang') || 'en') === 'hi' ? 'hi-IN' : 'en-US';
        utter.lang = lang;
        const v = pickVoiceForLang(lang);
        if (v) utter.voice = v;
        utter.rate = 1.0; utter.pitch = 1.0; utter.volume = 1.0;
        utter.onend = () => { i++; next(); };
        synth.speak(utter);
      } else {
        if (callback) callback();
      }
    })();
  }

  function listen(onSuccess, onFailure) {
    if (!recog) { if (onFailure) onFailure(); return; }
    recog.start();
    recog.onresult = e => {
      const answer = e.results[0][0].transcript;
      if (answer && answer.trim() !== "") {
        if (onSuccess) onSuccess(answer);
      } else { if (onFailure) onFailure(); }
    };
    recog.onerror = () => { if (onFailure) onFailure(); };
  }

  let index = 0;
  window.interviewStarted = false;
  let weightCheckInterval = null;
  let sensorPhase = 'weight'; // weight -> heartbeat -> temperature -> photo -> complete
  let sensorReadingComplete = false; // Prevent repetition
  let capturedVitals = null;
  let qrScannerActive = false;
  let scannedPatientData = null;

  function updateWeightBadge(w) {
    try {
      const el = document.getElementById('weightText');
      if (!el) return;
      const num = Number(w);
      if (Number.isFinite(num) && num > 0) {
        el.textContent = `Weight: ${num.toFixed(3)} kg`;
      } else {
        el.textContent = 'Weight: -- kg';
      }
    } catch {}
  }

  function ask() {
    const use = getActiveQuestions();
    if (index < use.length) {
      const q = use[index];
      setDisplayIfExists('questionDisplay', q.prompt);
      
      // Check if this is a QR scan question
      if (q.type === 'qr_scan') {
        // Speak the QR prompt before starting scanning
        speakChunked(q.prompt, () => {
          startQRCodeScanning();
        });
      } else {
        speakChunked(q.prompt, () => {
          setTimeout(() => {
            listen(
              answer => {
                const el = document.getElementById(q.field);
                if (el) el.innerText = answer;
                setDisplayIfExists('answerDisplay', answer);
                index++;
                ask();
              },
              () => {
                const lang = sessionStorage.getItem('qa_lang') || 'en';
                const retry = (lang === 'hi') ? 'मुझे समझ नहीं आया, कृपया दोहराएँ।' : "I didn't catch that. Could you please repeat?";
                speakChunked(retry, () => ask());
              }
            );
          }, 100);
        });
      }
    } else {
      // Questions completed, start sensor phase
      startSensorPhase();
    }
  }

  function startQRCodeScanning() {
    qrScannerActive = true;
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const scanningMsg = (lang === 'hi') ? 
      'QR कोड स्कैन कर रहा हूं... कृपया QR कोड को कैमरे के सामने रखें।' : 
      'Scanning QR code... Please hold your QR code in front of the camera.';
    
    setDisplayIfExists('answerDisplay', 'Scanning QR code...');
    
    // Start QR code detection
    startQRDetection();
  }

  function startQRDetection() {
    if (!qrScannerActive) return;
    // Real-time QR decoding using jsQR from the browser camera stream
    const video = document.getElementById('browserCamera');
    const canvasEl = document.getElementById('photoCanvas') || document.createElement('canvas');
    const ctx = canvasEl.getContext && canvasEl.getContext('2d');
    let attempts = 0;
    const maxAttempts = 200; // ~60s at 300ms

    function scan() {
      if (!qrScannerActive) return;
      try {
        if (video && video.readyState >= 2 && video.videoWidth && video.videoHeight && ctx) {
          canvasEl.width = video.videoWidth;
          canvasEl.height = video.videoHeight;
          ctx.drawImage(video, 0, 0, canvasEl.width, canvasEl.height);
          try {
            const imageData = ctx.getImageData(0, 0, canvasEl.width, canvasEl.height);
            if (typeof jsQR !== 'undefined' && imageData && imageData.data) {
              const result = jsQR(imageData.data, imageData.width, imageData.height);
              if (result && result.data) {
                // QR detected
                qrScannerActive = false;
                processQRCodeData(result.data);
                return;
              }
            }
          } catch (e) {
            // continue scanning on errors
          }
        }
      } catch (e) {}

      attempts++;
      if (attempts < maxAttempts) {
        setTimeout(scan, 300);
      } else {
        handleQRScanError('QR code not detected');
      }
    }

    scan();
  }

  function simulateQRCodeDetection() {
    // This is a demo function - in real implementation, this would be replaced with actual QR code scanning
    // For now, we'll simulate finding a patient with ID 1
    const mockQRData = JSON.stringify({
      "patient_id": 1,
      "name": "Demo Patient",
      "age": 30,
      "gender": "Male",
      "type": "patient_id"
    });
    
    processQRCodeData(mockQRData);
  }

  function processQRCodeData(qrData) {
    // Send QR data to server for verification
    fetch('/api/verify-qr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qr_data: qrData })
    })
    .then(response => response.json())
    .then(result => {
      if (result.status === 'success') {
        scannedPatientData = result;
        qrScannerActive = false;
        
        const lang = sessionStorage.getItem('qa_lang') || 'en';
        const successMsg = (lang === 'hi') ? 
          `QR कोड स्कैन सफल! नमस्ते ${result.patient_name}` : 
          `code scanned successfully! Hello ${result.patient_name}.`;
        
        setDisplayIfExists('answerDisplay', successMsg);
        setDisplayIfExists('questionDisplay', successMsg);
        
        // Store patient ID for later use
        const patientIdEl = document.getElementById('patientId');
        if (patientIdEl) patientIdEl.innerText = result.patient_id.toString();
        // Also store/display patient name so we don't need to ask again
        const nameEl = document.getElementById('name');
        if (nameEl && result.patient_name) nameEl.innerText = result.patient_name;
        
        // Speak success, then move to next question
        try {
          speakChunked(successMsg, () => {
            index++;
            setTimeout(() => ask(), 500);
          });
        } catch (e) {
          index++;
          setTimeout(() => ask(), 500);
        }
      } else {
        handleQRScanError(result.error);
      }
    })
    .catch(error => {
      console.error('QR verification error:', error);
      handleQRScanError('Failed to verify QR code');
    });
  }

  function handleQRScanError(error) {
    qrScannerActive = false;
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const errorMsg = (lang === 'hi') ? 
      'QR कोड पढ़ने में त्रुटि। कृपया फिर से कोशिश करें।' : 
      'Error reading QR code. Please try again.';
    
    setDisplayIfExists('answerDisplay', errorMsg);
    setDisplayIfExists('questionDisplay', errorMsg);
    
    // Retry after 3 seconds
    setTimeout(() => {
      startQRCodeScanning();
    }, 3000);
  }

  function startSensorPhase() {
    sensorPhase = 'heartbeat';
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const msg = (lang === 'hi') ? 
      'अब कृपया अपनी उंगली हृदय गति सेंसर पर रखें। मैं 3 सेकंड तक पढ़ूंगा।' : 
      'Now please place your finger on the heartbeat sensor. I will read for 3 seconds.';
    
    setDisplayIfExists('questionDisplay', msg);
    speakChunked(msg, () => {
      // Show popup video for heartbeat sensor
      const title = (lang === 'hi') ? 'हृदय गति सेंसर' : 'Heartbeat Sensor';
      const instruction = (lang === 'hi') ? 
        'कृपया अपनी उंगली सेंसर पर रखें' : 
        'Please place your finger on the sensor';
      
      if (typeof showSensorVideoPopup === 'function') {
        showSensorVideoPopup(title, instruction, 'heartbeat');
      } else {
        // Fallback to direct reading if popup not available
        startHeartbeatReading();
      }
    });
  }

  function startHeartbeatReading() {
    if (sensorPhase !== 'heartbeat') {
      console.log('Heartbeat reading already completed or not in heartbeat phase');
      return;
    }
    
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    let attempts = 0;
    const maxAttempts = 100; // ~30-50 seconds depending on interval
    const pollIntervalMs = 500;

    function updateDisplayWaiting() {
      const msg = (lang === 'hi') ? 
        'उंगली का पता लगाने की प्रतीक्षा कर रहा हूं...' : 
        'Waiting for finger detection...';
      setDisplayIfExists('questionDisplay', msg);
      setVitalsStatus((lang === 'hi') ? 'Waiting for captured vitals...' : 'Waiting for captured vitals...');
    }

    function showCaptured(v) {
      const msg = (lang === 'hi') ? 
        `कॅप्चर किया गया: HR ${v.heart_rate || '--'} bpm, SpO₂ ${v.spo2 || '--'}%, Temp ${v.temperature != null ? v.temperature.toFixed(1) : '--'}°C` : 
        `Captured: HR ${v.heart_rate || '--'} bpm, SpO₂ ${v.spo2 || '--'}%, Temp ${v.temperature != null ? v.temperature.toFixed(1) : '--'}°C`;
      setDisplayIfExists('questionDisplay', msg);
      const box = document.getElementById('capturedVitals');
      if (box) {
        const hr = v.heart_rate != null ? v.heart_rate : '--';
        const sp = v.spo2 != null ? v.spo2 : '--';
        const bt = v.temperature != null ? v.temperature.toFixed(1) : '--';
        box.textContent = `HR: ${hr} bpm | SpO₂: ${sp}% | Temp: ${bt}°C`;
      }
      updateWeightBadge(v.weight);
      const statusTxt = (lang === 'hi') ?
        `Captured HR ${v.heart_rate || '--'}, SpO₂ ${v.spo2 || '--'}, Temp ${v.temperature != null ? v.temperature.toFixed(1) : '--'}°C` :
        `Captured HR ${v.heart_rate || '--'}, SpO₂ ${v.spo2 || '--'}, Temp ${v.temperature != null ? v.temperature.toFixed(1) : '--'}°C`;
      setVitalsStatus(statusTxt);
    }

    updateDisplayWaiting();

    const poll = () => {
      attempts++;
      fetch('/api/sensor')
        .then(r => r.json())
        .then(s => {
          const hr = s && s.heart_rate != null ? Number(s.heart_rate) : 0;
          if (hr > 0) {
            capturedVitals = {
              heart_rate: hr,
              spo2: s && s.spo2 != null ? Number(s.spo2) : null,
              temperature: s && s.temperature != null ? Number(s.temperature) : null,
              env_temperature: s && s.env_temperature != null ? Number(s.env_temperature) : null,
              humidity: s && s.humidity != null ? Number(s.humidity) : null,
              weight: s && s.weight != null ? Number(s.weight) : null,
              timestamp: s && s.timestamp ? s.timestamp : null
            };
            try { window.capturedVitals = capturedVitals; } catch {}
            showCaptured(capturedVitals);
            setTimeout(() => {
              sensorPhase = 'temperature';
              startTemperaturePhase();
            }, 1000);
            return;
          }
          if (attempts < maxAttempts) {
            setTimeout(poll, pollIntervalMs);
          } else {
            sensorPhase = 'temperature';
            setVitalsStatus((lang === 'hi') ? 'Timeout, continuing...' : 'Timeout, continuing...');
            startTemperaturePhase();
          }
        })
        .catch(() => {
          if (attempts < maxAttempts) {
            setTimeout(poll, pollIntervalMs);
          } else {
            sensorPhase = 'temperature';
            setVitalsStatus((lang === 'hi') ? 'Timeout, continuing...' : 'Timeout, continuing...');
            startTemperaturePhase();
          }
        });
    };

    poll();
  }

  // Make functions globally accessible
  window.startHeartbeatReading = startHeartbeatReading;

  function startTemperaturePhase() {
    sensorPhase = 'temperature';
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const msg = (lang === 'hi') ? 
      'अब कृपया तापमान सेंसर को अपने माथे के बीच में रखें।' : 
      'Now please place the temperature sensor on the middle of your forehead.';
    
    setDisplayIfExists('questionDisplay', msg);
    speakChunked(msg, () => {
      // Show popup video for temperature sensor
      const title = (lang === 'hi') ? 'तापमान सेंसर' : 'Temperature Sensor';
      const instruction = (lang === 'hi') ? 
        'कृपया सेंसर को माथे के बीच में रखें' : 
        'Please place the sensor on your forehead';
      
      if (typeof showSensorVideoPopup === 'function') {
        showSensorVideoPopup(title, instruction, 'temperature');
      } else {
        // Fallback to direct reading if popup not available
        waitForTemperature();
      }
    });
  }

  function waitForTemperature() {
    if (sensorPhase !== 'temperature') {
      console.log('Temperature reading already completed or not in temperature phase');
      return;
    }
    
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const waitingMsg = (lang === 'hi') ?
      'तापमान पढ़ रहा हूं... कृपया सेंसर को माथे पर रखे रखें।' :
      'Reading temperature... Please keep the sensor on your forehead.';
    setDisplayIfExists('questionDisplay', waitingMsg);

    let attempts = 0;
    const maxAttempts = 100; // up to ~50s
    const pollIntervalMs = 500;

    function showCapturedTemp(tempC, s) {
      const displayMsg = (lang === 'hi') ?
        `कॅप्चर किया गया तापमान: ${tempC.toFixed(1)}°C` :
        `Captured temperature: ${tempC.toFixed(1)}°C`;
      setDisplayIfExists('questionDisplay', displayMsg);
      if (!capturedVitals || typeof capturedVitals !== 'object') capturedVitals = {};
      capturedVitals.temperature = Number(tempC);
      if (s) {
        if (s.env_temperature != null) capturedVitals.env_temperature = Number(s.env_temperature);
        if (s.humidity != null) capturedVitals.humidity = Number(s.humidity);
        if (s.weight != null) updateWeightBadge(Number(s.weight));
      }
      const box = document.getElementById('capturedVitals');
      if (box) {
        const hr = capturedVitals.heart_rate != null ? capturedVitals.heart_rate : '--';
        const sp = capturedVitals.spo2 != null ? capturedVitals.spo2 : '--';
        const bt = capturedVitals.temperature != null ? capturedVitals.temperature.toFixed(1) : '--';
        box.textContent = `HR: ${hr} bpm | SpO₂: ${sp}% | Temp: ${bt}°C`;
      }
      const statusTxt = (lang === 'hi') ?
        `Captured HR ${capturedVitals.heart_rate || '--'}, SpO₂ ${capturedVitals.spo2 || '--'}, Temp ${capturedVitals.temperature != null ? capturedVitals.temperature.toFixed(1) : '--'}°C` :
        `Captured HR ${capturedVitals.heart_rate || '--'}, SpO₂ ${capturedVitals.spo2 || '--'}, Temp ${capturedVitals.temperature != null ? capturedVitals.temperature.toFixed(1) : '--'}°C`;
      setVitalsStatus(statusTxt);
    }

    const poll = () => {
      attempts++;
      fetch('/api/sensor')
        .then(r => r.json())
        .then(s => {
          const temp = s && s.temperature != null ? Number(s.temperature) : 0;
          if (temp > 30) {
            showCapturedTemp(temp, s);
            setTimeout(() => {
              sensorPhase = 'photo';
              startPhotoPhase();
            }, 1000);
            return;
          }
          if (attempts < maxAttempts) {
            setTimeout(poll, pollIntervalMs);
          } else {
            // Timeout: proceed without captured temperature
            sensorPhase = 'photo';
            setVitalsStatus((lang === 'hi') ? 'Timeout, continuing...' : 'Timeout, continuing...');
            startPhotoPhase();
          }
        })
        .catch(() => {
          if (attempts < maxAttempts) {
            setTimeout(poll, pollIntervalMs);
          } else {
            sensorPhase = 'photo';
            setVitalsStatus((lang === 'hi') ? 'Timeout, continuing...' : 'Timeout, continuing...');
            startPhotoPhase();
          }
        });
    };

    poll();
  }

  // Make functions globally accessible
  window.waitForTemperature = waitForTemperature;

  function startPhotoPhase() {
    if (sensorPhase !== 'photo' || sensorReadingComplete) {
      console.log('Photo phase already completed or not in photo phase');
      return;
    }
    
    sensorPhase = 'photo';
    sensorReadingComplete = true; // Prevent repetition
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const msg = (lang === 'hi') ? 
      'सभी सेंसर रीडिंग पूरी हो गई। अब मैं आपकी तस्वीर लूंगा।' : 
      'All sensor readings complete. Now I will take your picture.';
    
    setDisplayIfExists('questionDisplay', msg);
    speakChunked(msg, () => {
      setTimeout(() => {
        // Show countdown for photo
        const countdownMsg = (lang === 'hi') ? 
          'तस्वीर ले रहा हूं... 3... 2... 1...' : 
          'Taking photo... 3... 2... 1...';
        setDisplayIfExists('questionDisplay', countdownMsg);
        speakChunked(countdownMsg, () => {
          captureAndSubmit();
        });
      }, 2000);
    });
  }

  function captureAndSubmit() {
    const get = id => (document.getElementById(id)?.innerText || '').trim();
    const fields = [
      "qrScan","patientId","name","age","gender","contact","address","medicalHistory","chiefComplaint","painDescription",
      "additionalFeelings","emergencyName","emergencyRelation","emergencyGender","emergencyContact","emergencyAddress"
    ];
    fields.forEach(id => sessionStorage.setItem('qa_' + id, get(id)));

    // Capture photo first
    capturePhoto().then(() => {
      // After photo is captured, collect sensor data and submit
      setTimeout(() => {
        const useCaptured = capturedVitals && typeof capturedVitals === 'object';
        const withSensor = (s) => {
          const cToF = c => {
            const n = Number(c);
            return Number.isFinite(n) ? (n * 9/5 + 32) : null;
          };
          const payload = {
            photo: sessionStorage.getItem('qa_photo') || null,
            patient_id: get('patientId'),
            name: get('name'),
            age: get('age'),
            gender: get('gender'),
            contact: get('contact'),
            address: get('address'),
            chief_complaint: get('chiefComplaint'),
            pain_description: get('painDescription'),
            additional_symptoms: get('additionalFeelings'),
            medical_history: get('medicalHistory'),
            emergency_name: get('emergencyName'),
            emergency_relation: get('emergencyRelation'),
            emergency_gender: get('emergencyGender'),
            emergency_contact: get('emergencyContact'),
            emergency_address: get('emergencyAddress'),
            heart_rate: s && s.heart_rate != null ? Number(s.heart_rate) : null,
            spo2: s && s.spo2 != null ? Number(s.spo2) : null,
            body_temp_f: s && s.temperature != null ? cToF(s.temperature) : null,
            env_temp_f: s && s.env_temperature != null ? cToF(s.env_temperature) : null,
            humidity_percent: s && s.humidity != null ? Number(s.humidity) : null,
            weight_kg: s && s.weight != null ? Number(s.weight) : null
          };
          
          console.log('📊 Submitting patient data:', payload);
          console.log('📸 Photo filename:', payload.photo);
          // Use robot-patient endpoint to link to existing patient profile
          return fetch('/api/robot-patient', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        };
        const p = useCaptured
          ? Promise.resolve(capturedVitals)
          : fetch('/api/sensor').then(r => r.json());
        p.then(s => withSensor(s))
          .catch(() => {})
          .finally(() => { 
            showClosingRemarks();
          });
      }, 1000);
    });
  }

  function capturePhoto() {
    return new Promise((resolve) => {
      console.log('📸 Starting photo capture...');
      
      // Try browser camera first
      if (typeof captureBrowserPhoto === 'function') {
        try {
          console.log('📸 Using browser camera...');
          captureBrowserPhoto();
          // Wait longer for the photo to be processed and uploaded
          setTimeout(() => {
            const photoFilename = sessionStorage.getItem('qa_photo');
            console.log('📸 Browser camera photo filename:', photoFilename);
            if (!photoFilename) {
              console.log('📸 No photo filename found, trying external camera...');
              fallbackPhotoCapture().then(resolve);
            } else {
              console.log('✅ Photo captured successfully:', photoFilename);
              resolve();
            }
          }, 5000); // Increased timeout to 5 seconds
        } catch (error) {
          console.error('❌ Browser camera failed:', error);
          // Fallback to external camera
          fallbackPhotoCapture().then(resolve);
        }
      } else {
        console.log('📸 Using external camera fallback...');
        // Fallback to external camera
        fallbackPhotoCapture().then(resolve);
      }
    });
  }

  function fallbackPhotoCapture() {
    return new Promise((resolve) => {
      console.log('📸 Attempting external camera capture...');
      fetch('/take_picture')
        .then(res => res.json())
        .then(data => { 
          if (data && data.status === 'success' && data.filename) {
            sessionStorage.setItem('qa_photo', data.filename);
            console.log('✅ Photo captured via external camera:', data.filename);
          } else {
            console.error('❌ Photo capture failed:', data);
            // Generate a placeholder filename if capture fails
            const placeholderFilename = `patient_${Date.now()}.jpg`;
            sessionStorage.setItem('qa_photo', placeholderFilename);
            console.log('📸 Using placeholder filename:', placeholderFilename);
          }
          resolve();
        })
        .catch(error => {
          console.error('❌ Photo capture error:', error);
          // Generate a placeholder filename if capture fails
          const placeholderFilename = `patient_${Date.now()}.jpg`;
          sessionStorage.setItem('qa_photo', placeholderFilename);
          console.log('📸 Using placeholder filename after error:', placeholderFilename);
          resolve();
        });
    });
  }

  function showClosingRemarks() {
    sensorPhase = 'complete';
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const msg = (lang === 'hi') ? 
      'धन्यवाद! आपकी जांच पूरी हो गई है। डॉक्टर जल्द ही आपसे मिलेंगे। कृपया प्रतीक्षा करें।' : 
      'Thank you! Your examination is complete. The doctor will see you shortly. Please wait.';
    
    setDisplayIfExists('questionDisplay', msg);
    speakChunked(msg, () => {
      // Refresh page after 5 seconds for next patient
      setTimeout(() => {
        window.location.reload();
      }, 5000);
    });
  }

  function checkWeightAndStart() {
    fetch('/api/sensor')
      .then(r => r.json())
      .then(s => {
        const weight = s && s.weight != null ? Number(s.weight) : 0;
        updateWeightBadge(weight);
        if (weight > 10 && !window.interviewStarted) {
          // Weight detected, start interview
          window.interviewStarted = true;
          if (weightCheckInterval) {
            clearInterval(weightCheckInterval);
            weightCheckInterval = null;
          }
          
          const lang = sessionStorage.getItem('qa_lang') || 'en';
          const msg = (lang === 'hi') ? 
            'नमस्ते! मैं देख रहा हूं कि आप यहां हैं। मैं आपकी मदद के लिए यहां हूं।' : 
            'Hello! I can see you are here. I am here to help you.';
          
          setDisplayIfExists('questionDisplay', msg);
          speakChunked(msg, () => {
            setTimeout(() => {
              index = 0;
              ask();
            }, 2000);
          });
        }
      })
      .catch(() => {});
  }

  function startWeightMonitoring() {
    if (weightCheckInterval) return; // Already monitoring
    
    weightCheckInterval = setInterval(checkWeightAndStart, 2000); // Check every 2 seconds
    
    const lang = sessionStorage.getItem('qa_lang') || 'en';
    const msg = (lang === 'hi') ? 
      'कृपया वजन सेंसर पर खड़े हों। मैं आपका वजन मापूंगा।' : 
      'Please stand on the weight sensor. I will measure your weight.';
    
    setDisplayIfExists('questionDisplay', msg);
    speakChunked(msg, () => {});
  }

  window.start = function () {
    index = 0;
    window.interviewStarted = true;
    ask();
  };

  // Make popup function globally accessible
  window.showSensorVideoPopup = function(title, instruction, sensorType) {
    // This will be overridden by the HTML template function
    console.log('showSensorVideoPopup called:', title, instruction, sensorType);
  };

  // Auto-start weight monitoring when page loads
  window.addEventListener('DOMContentLoaded', function() {
    // Start weight monitoring automatically
    startWeightMonitoring();
  });

  // Clean up interval when page unloads
  window.addEventListener('beforeunload', function() {
    if (weightCheckInterval) {
      clearInterval(weightCheckInterval);
    }
  });
})();



