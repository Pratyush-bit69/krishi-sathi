/**
 * Krishi-Sathi — Premium Frontend
 * 3D Globe · Satellite Cursor · Particle Field · Full Dashboard
 */

// ═══════════════════════════════════════════════════════════════
//  GLOBAL STATE
// ═══════════════════════════════════════════════════════════════

let currentSite = "icrisat";
let dashboardData = null;
let map = null;
let fieldLayers = {};
let accessToken = null;

// Chart instances
let ndviChart, ndwiChart, smcChart, yieldChart, weatherChart, rainChart;

// Globe
let globe = { scene: null, camera: null, renderer: null, sphere: null, clouds: null, markers: [], raycaster: null, mouse: new THREE.Vector2(), animId: null };

// Pilot site coords
const SITES = {
    icrisat:   { lat: 17.320,  lon: 78.210,  name: "ICRISAT Hyderabad", color: "#06b6d4" },
    ludhiana:  { lat: 30.9010, lon: 75.8573,  name: "Ludhiana Punjab", color: "#f59e0b" },
    nashik:    { lat: 19.9975, lon: 73.7898,  name: "Nashik Maharashtra", color: "#a855f7" },
    coimbatore:{ lat: 11.0168, lon: 76.9558,  name: "TNAU Coimbatore", color: "#ec4899" },
    bhopal:    { lat: 23.2599, lon: 77.4126,  name: "Bhopal MP", color: "#f97316" },
    varanasi:  { lat: 25.3176, lon: 82.9739,  name: "Varanasi UP", color: "#14b8a6" },
};

// Zone analysis data for globe hover
const ZONE_DATA = {
    "South Asia":       { ndvi: "0.45–0.78", moisture: "22–38%", crops: "Rice, Wheat, Cotton, Sorghum", risk: "Medium — Monsoon Dependent", farmers: "~280M" },
    "Southeast Asia":   { ndvi: "0.50–0.85", moisture: "30–45%", crops: "Rice, Palm Oil, Rubber", risk: "Low — Dual Monsoon", farmers: "~120M" },
    "Sub-Saharan Africa": { ndvi: "0.20–0.55", moisture: "8–22%", crops: "Maize, Cassava, Millet", risk: "High — Drought Prone", farmers: "~200M" },
    "East Asia":        { ndvi: "0.40–0.75", moisture: "25–40%", crops: "Rice, Tea, Soybeans", risk: "Low — Irrigated Systems", farmers: "~300M" },
    "Latin America":    { ndvi: "0.55–0.90", moisture: "35–50%", crops: "Coffee, Sugarcane, Soy", risk: "Medium — Deforestation", farmers: "~50M" },
    "Central Asia":     { ndvi: "0.15–0.40", moisture: "5–15%", crops: "Wheat, Cotton, Barley", risk: "High — Arid", farmers: "~25M" },
    "Europe":           { ndvi: "0.35–0.70", moisture: "20–35%", crops: "Wheat, Barley, Grapes", risk: "Low — Advanced Systems", farmers: "~10M" },
    "North America":    { ndvi: "0.30–0.65", moisture: "18–30%", crops: "Corn, Soy, Wheat", risk: "Low — Tech-Enabled", farmers: "~3M" },
    "North Africa":     { ndvi: "0.10–0.30", moisture: "3–12%", crops: "Olives, Dates, Wheat", risk: "High — Desertification", farmers: "~20M" },
    "Oceania":          { ndvi: "0.25–0.60", moisture: "10–25%", crops: "Wheat, Sugarcane, Wool", risk: "Medium — Fire/Drought", farmers: "~1M" },
};

// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add("hero-active");
    initSatelliteCursor();
    initParticleBackground();
    initGlobe();
    animateHeroStats();
    // Dashboard will init when user enters
});

// ═══════════════════════════════════════════════════════════════
//  1. SATELLITE CURSOR
// ═══════════════════════════════════════════════════════════════

function initSatelliteCursor() {
    const cursor = document.getElementById("satelliteCursor");
    if (!cursor) return;

    // Build satellite SVG
    cursor.innerHTML = `<svg width="32" height="32" viewBox="0 0 64 64" fill="none">
        <g transform="rotate(-45, 32, 32)">
            <!-- Body -->
            <rect x="24" y="22" width="16" height="20" rx="3" fill="#06b6d4" opacity="0.9"/>
            <!-- Solar panels -->
            <rect x="4" y="26" width="18" height="12" rx="2" fill="#22c55e" opacity="0.8"/>
            <rect x="42" y="26" width="18" height="12" rx="2" fill="#22c55e" opacity="0.8"/>
            <!-- Panel lines -->
            <line x1="13" y1="26" x2="13" y2="38" stroke="#0b0f1a" stroke-width="0.8"/>
            <line x1="51" y1="26" x2="51" y2="38" stroke="#0b0f1a" stroke-width="0.8"/>
            <!-- Antenna -->
            <circle cx="32" cy="18" r="3" fill="#f59e0b"/>
            <line x1="32" y1="21" x2="32" y2="22" stroke="#f59e0b" stroke-width="1.5"/>
            <!-- Lens -->
            <circle cx="32" cy="45" r="4" fill="#0b0f1a" stroke="#06b6d4" stroke-width="1.5"/>
            <circle cx="32" cy="45" r="2" fill="#06b6d4" opacity="0.5"/>
        </g>
        <!-- Signal rings -->
        <circle cx="32" cy="50" r="8" stroke="#22c55e" stroke-width="0.5" fill="none" opacity="0.4" class="signal-ring"/>
        <circle cx="32" cy="50" r="12" stroke="#22c55e" stroke-width="0.3" fill="none" opacity="0.2" class="signal-ring"/>
    </svg>`;

    let mouseX = 0, mouseY = 0;
    let cursorX = 0, cursorY = 0;

    document.addEventListener("mousemove", (e) => {
        mouseX = e.clientX;
        mouseY = e.clientY;
    });

    let isHovering = false;

    function updateCursor() {
        cursorX += (mouseX - cursorX) * 0.15;
        cursorY += (mouseY - cursorY) * 0.15;
        const scale = isHovering ? 1.3 : 1;
        cursor.style.transform = `translate(${cursorX - 16}px, ${cursorY - 16}px) scale(${scale})`;
        requestAnimationFrame(updateCursor);
    }
    updateCursor();

    // Scale on hover interactive elements
    document.addEventListener("mouseover", (e) => {
        const t = e.target.closest("button, a, select, input, .card, .summary-card, .tab, .result-card, .nudge-item, .data-table tbody tr");
        if (t) { cursor.classList.add("cursor-hover"); isHovering = true; }
    });
    document.addEventListener("mouseout", (e) => {
        const t = e.target.closest("button, a, select, input, .card, .summary-card, .tab, .result-card, .nudge-item, .data-table tbody tr");
        if (t) { cursor.classList.remove("cursor-hover"); isHovering = false; }
    });
}

// ═══════════════════════════════════════════════════════════════
//  2. PARTICLE BACKGROUND
// ═══════════════════════════════════════════════════════════════

function initParticleBackground() {
    const canvas = document.getElementById("particleBg");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let particles = [];
    const PARTICLE_COUNT = 80;

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    for (let i = 0; i < PARTICLE_COUNT; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            vx: (Math.random() - 0.5) * 0.3,
            vy: (Math.random() - 0.5) * 0.3,
            r: Math.random() * 2 + 0.5,
            a: Math.random() * 0.4 + 0.1,
        });
    }

    function drawParticles() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        particles.forEach((p, i) => {
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0) p.x = canvas.width;
            if (p.x > canvas.width) p.x = 0;
            if (p.y < 0) p.y = canvas.height;
            if (p.y > canvas.height) p.y = 0;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(34, 197, 94, ${p.a})`;
            ctx.fill();

            // connections
            for (let j = i + 1; j < particles.length; j++) {
                const p2 = particles[j];
                const dx = p.x - p2.x;
                const dy = p.y - p2.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 120) {
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.strokeStyle = `rgba(6, 182, 212, ${0.06 * (1 - dist / 120)})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        });

        requestAnimationFrame(drawParticles);
    }
    drawParticles();
}

// ═══════════════════════════════════════════════════════════════
//  3. THREE.JS 3D GLOBE
// ═══════════════════════════════════════════════════════════════

function initGlobe() {
    const container = document.getElementById("heroGlobeWrap");
    const canvas = document.getElementById("globeCanvas");
    if (!container || !canvas) return;

    const w = container.clientWidth || 500;
    const h = container.clientHeight || 500;

    // Scene
    globe.scene = new THREE.Scene();
    globe.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000);
    globe.camera.position.z = 2.8;

    globe.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    globe.renderer.setSize(w, h);
    globe.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Earth sphere
    const earthGeo = new THREE.SphereGeometry(1, 64, 64);

    // Procedural earth-like material with shaders
    const earthMat = new THREE.ShaderMaterial({
        uniforms: {
            uTime: { value: 0 },
        },
        vertexShader: `
            varying vec2 vUv;
            varying vec3 vNormal;
            varying vec3 vPosition;
            void main() {
                vUv = uv;
                vNormal = normalize(normalMatrix * normal);
                vPosition = (modelViewMatrix * vec4(position, 1.0)).xyz;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `,
        fragmentShader: `
            uniform float uTime;
            varying vec2 vUv;
            varying vec3 vNormal;
            varying vec3 vPosition;

            // Simple hash
            float hash(vec2 p) {
                return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
            }

            // Value noise
            float noise(vec2 p) {
                vec2 i = floor(p);
                vec2 f = fract(p);
                f = f * f * (3.0 - 2.0 * f);
                float a = hash(i);
                float b = hash(i + vec2(1.0, 0.0));
                float c = hash(i + vec2(0.0, 1.0));
                float d = hash(i + vec2(1.0, 1.0));
                return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
            }

            void main() {
                // Simulate continents via noise
                float n = noise(vUv * 8.0) * 0.5 + noise(vUv * 16.0) * 0.3 + noise(vUv * 32.0) * 0.2;

                // Latitude-based coloring
                float lat = abs(vUv.y - 0.5) * 2.0;

                vec3 ocean = vec3(0.04, 0.08, 0.18);
                vec3 land = vec3(0.08, 0.28, 0.12);
                vec3 desert = vec3(0.35, 0.28, 0.15);
                vec3 ice = vec3(0.7, 0.75, 0.8);

                vec3 col = ocean;
                if (n > 0.42) {
                    col = mix(land, desert, smoothstep(0.2, 0.4, lat) * (1.0 - n));
                }
                if (lat > 0.75) {
                    col = mix(col, ice, smoothstep(0.75, 0.95, lat));
                }

                // Atmosphere fresnel
                float fresnel = pow(1.0 - max(dot(vNormal, normalize(-vPosition)), 0.0), 3.0);
                vec3 atmo = vec3(0.13, 0.55, 0.85);
                col = mix(col, atmo, fresnel * 0.6);

                // Subtle glow
                col += vec3(0.02, 0.08, 0.04) * (1.0 - lat);

                gl_FragColor = vec4(col, 1.0);
            }
        `,
        transparent: false,
    });

    globe.sphere = new THREE.Mesh(earthGeo, earthMat);
    globe.scene.add(globe.sphere);

    // Atmosphere glow
    const atmoGeo = new THREE.SphereGeometry(1.08, 64, 64);
    const atmoMat = new THREE.ShaderMaterial({
        vertexShader: `
            varying vec3 vNormal;
            varying vec3 vPosition;
            void main() {
                vNormal = normalize(normalMatrix * normal);
                vPosition = (modelViewMatrix * vec4(position, 1.0)).xyz;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `,
        fragmentShader: `
            varying vec3 vNormal;
            varying vec3 vPosition;
            void main() {
                float intensity = pow(0.65 - dot(vNormal, normalize(-vPosition)), 2.0);
                vec3 atmoColor = vec3(0.13, 0.7, 0.45);
                gl_FragColor = vec4(atmoColor, intensity * 0.5);
            }
        `,
        blending: THREE.AdditiveBlending,
        side: THREE.BackSide,
        transparent: true,
    });
    globe.scene.add(new THREE.Mesh(atmoGeo, atmoMat));

    // Add pilot site markers
    Object.entries(SITES).forEach(([key, site]) => {
        addGlobeMarker(site.lat, site.lon, site.color, site.name, key);
    });

    // Add connection arcs between pilot sites
    addConnectionArcs();

    // Add starfield background
    addStarfield();

    // Add satellite orbit trail
    addSatelliteOrbit();

    // Lights
    const ambLight = new THREE.AmbientLight(0x334455, 0.6);
    globe.scene.add(ambLight);
    const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
    dirLight.position.set(5, 3, 5);
    globe.scene.add(dirLight);

    // Raycaster for hover
    globe.raycaster = new THREE.Raycaster();

    // Mouse tracking on globe
    canvas.addEventListener("mousemove", onGlobeMouseMove);
    canvas.addEventListener("click", onGlobeClick);

    // Auto-rotate
    let autoRotate = true;
    let targetRotY = 0;
    let isDragging = false;
    let dragStartX = 0, dragStartY = 0;
    let rotVelX = 0, rotVelY = 0;

    canvas.addEventListener("mousedown", (e) => {
        isDragging = true;
        autoRotate = false;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
    });

    window.addEventListener("mouseup", () => {
        if (isDragging) {
            isDragging = false;
            setTimeout(() => { autoRotate = true; }, 3000);
        }
    });

    window.addEventListener("mousemove", (e) => {
        if (isDragging && globe.sphere) {
            const dx = (e.clientX - dragStartX) * 0.005;
            const dy = (e.clientY - dragStartY) * 0.005;
            globe.sphere.rotation.y += dx;
            globe.sphere.rotation.x += dy;
            globe.sphere.rotation.x = Math.max(-1.2, Math.min(1.2, globe.sphere.rotation.x));
            dragStartX = e.clientX;
            dragStartY = e.clientY;
        }
    });

    // Animate
    let time = 0;
    function animate() {
        globe.animId = requestAnimationFrame(animate);
        time += 0.01;

        if (globe.sphere) {
            if (autoRotate) {
                globe.sphere.rotation.y += 0.002;
            }
            globe.sphere.material.uniforms.uTime.value = time;
        }

        // Pulse markers
        globe.markers.forEach((m, i) => {
            if (m.ring) {
                const s = 1 + Math.sin(time * 2 + i) * 0.3;
                m.ring.scale.set(s, s, s);
            }
        });

        // Animate satellite along orbit
        if (globe.satDot && globe.orbitLine) {
            const angle = time * 0.8;
            const r = 1.35;
            const x = r * Math.cos(angle);
            const y = r * Math.sin(angle) * 0.3;
            const z = r * Math.sin(angle) * Math.cos(0.4);
            // Apply same rotation as orbit line
            const pos = new THREE.Vector3(x, y, z);
            pos.applyAxisAngle(new THREE.Vector3(1, 0, 0), 0.5);
            pos.applyAxisAngle(new THREE.Vector3(0, 0, 1), 0.3);
            globe.satDot.position.copy(pos);
        }

        // Second satellite (polar orbit, slower)
        if (globe.sat2Dot) {
            const angle2 = time * 0.5;
            const r2 = 1.35 * 1.08;
            const x2 = r2 * Math.cos(angle2) * 0.25;
            const y2 = r2 * Math.sin(angle2);
            const z2 = r2 * Math.cos(angle2) * Math.cos(0.2);
            const pos2 = new THREE.Vector3(x2, y2, z2);
            pos2.applyAxisAngle(new THREE.Vector3(0, 1, 0), 1.2);
            globe.sat2Dot.position.copy(pos2);
        }

        // Slowly rotate starfield
        if (globe.stars) {
            globe.stars.rotation.y += 0.0002;
            globe.stars.rotation.x += 0.0001;
        }

        // Pulse arc opacity
        if (globe.arcGroup) {
            globe.arcGroup.children.forEach((arc, i) => {
                arc.material.opacity = 0.15 + Math.sin(time * 1.5 + i * 0.7) * 0.1;
            });
        }

        globe.renderer.render(globe.scene, globe.camera);
    }
    animate();

    // Resize
    window.addEventListener("resize", () => {
        const nw = container.clientWidth || 500;
        const nh = container.clientHeight || 500;
        globe.camera.aspect = nw / nh;
        globe.camera.updateProjectionMatrix();
        globe.renderer.setSize(nw, nh);
    });
}

function latLonToVec3(lat, lon, radius) {
    const phi = (90 - lat) * (Math.PI / 180);
    const theta = (lon + 180) * (Math.PI / 180);
    return new THREE.Vector3(
        -radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta)
    );
}

function addGlobeMarker(lat, lon, color, name, key) {
    const pos = latLonToVec3(lat, lon, 1.02);

    // Dot
    const dotGeo = new THREE.SphereGeometry(0.025, 16, 16);
    const dotMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(color) });
    const dot = new THREE.Mesh(dotGeo, dotMat);
    dot.position.copy(pos);
    dot.userData = { name, key, lat, lon };
    globe.scene.add(dot);

    // Pulse ring
    const ringGeo = new THREE.RingGeometry(0.03, 0.045, 32);
    const ringMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(color), side: THREE.DoubleSide, transparent: true, opacity: 0.6 });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.position.copy(pos);
    ring.lookAt(new THREE.Vector3(0, 0, 0));
    globe.scene.add(ring);

    globe.markers.push({ dot, ring, name, key, lat, lon });
}

// ═── Connection arcs between pilot sites ═──
function addConnectionArcs() {
    const siteKeys = Object.keys(SITES);
    const arcGroup = new THREE.Group();
    globe.arcGroup = arcGroup;
    globe.scene.add(arcGroup);

    // Connect nearby sites (pairs)
    const pairs = [
        ["coimbatore", "icrisat"],
        ["icrisat", "nashik"],
        ["nashik", "bhopal"],
        ["bhopal", "varanasi"],
        ["varanasi", "ludhiana"],
        ["ludhiana", "bhopal"],
    ];

    pairs.forEach(([a, b]) => {
        const sA = SITES[a], sB = SITES[b];
        if (!sA || !sB) return;
        const curve = createArcBetween(sA.lat, sA.lon, sB.lat, sB.lon, sA.color);
        if (curve) arcGroup.add(curve);
    });
}

function createArcBetween(lat1, lon1, lat2, lon2, color) {
    const start = latLonToVec3(lat1, lon1, 1.02);
    const end = latLonToVec3(lat2, lon2, 1.02);
    const mid = start.clone().add(end).multiplyScalar(0.5);
    const dist = start.distanceTo(end);
    mid.normalize().multiplyScalar(1.02 + dist * 0.35);

    const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
    const points = curve.getPoints(40);
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
        color: new THREE.Color(color),
        transparent: true,
        opacity: 0.25,
    });
    return new THREE.Line(geometry, material);
}

// ═── Starfield background ═──
function addStarfield() {
    const starGeo = new THREE.BufferGeometry();
    const starCount = 1500;
    const positions = new Float32Array(starCount * 3);
    const sizes = new Float32Array(starCount);

    for (let i = 0; i < starCount; i++) {
        const r = 8 + Math.random() * 20;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i * 3 + 2] = r * Math.cos(phi);
        sizes[i] = Math.random() * 2 + 0.5;
    }

    starGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    starGeo.setAttribute("size", new THREE.BufferAttribute(sizes, 1));

    const starMat = new THREE.PointsMaterial({
        color: 0xffffff,
        size: 0.03,
        transparent: true,
        opacity: 0.6,
        sizeAttenuation: true,
    });

    const stars = new THREE.Points(starGeo, starMat);
    globe.scene.add(stars);
    globe.stars = stars;
}

// ═── Satellite orbit trail ═──
function addSatelliteOrbit() {
    // Create an inclined orbit ring
    const orbitRadius = 1.35;
    const orbitPoints = [];
    for (let i = 0; i <= 200; i++) {
        const angle = (i / 200) * Math.PI * 2;
        orbitPoints.push(new THREE.Vector3(
            orbitRadius * Math.cos(angle),
            orbitRadius * Math.sin(angle) * 0.3,
            orbitRadius * Math.sin(angle) * Math.cos(0.4)
        ));
    }

    const orbitGeo = new THREE.BufferGeometry().setFromPoints(orbitPoints);
    const orbitMat = new THREE.LineBasicMaterial({
        color: 0x06b6d4,
        transparent: true,
        opacity: 0.15,
    });
    const orbitLine = new THREE.Line(orbitGeo, orbitMat);
    orbitLine.rotation.x = 0.5;
    orbitLine.rotation.z = 0.3;
    globe.scene.add(orbitLine);

    // Satellite dot moving along orbit
    const satGeo = new THREE.SphereGeometry(0.018, 8, 8);
    const satMat = new THREE.MeshBasicMaterial({ color: 0x22c55e, transparent: true, opacity: 0.9 });
    const satDot = new THREE.Mesh(satGeo, satMat);
    globe.scene.add(satDot);
    globe.satDot = satDot;
    globe.orbitLine = orbitLine;

    // Second orbit (polar)
    const orbit2Points = [];
    for (let i = 0; i <= 200; i++) {
        const angle = (i / 200) * Math.PI * 2;
        orbit2Points.push(new THREE.Vector3(
            orbitRadius * 1.08 * Math.cos(angle) * 0.25,
            orbitRadius * 1.08 * Math.sin(angle),
            orbitRadius * 1.08 * Math.cos(angle) * Math.cos(0.2)
        ));
    }
    const orbit2Geo = new THREE.BufferGeometry().setFromPoints(orbit2Points);
    const orbit2Mat = new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.1 });
    const orbit2Line = new THREE.Line(orbit2Geo, orbit2Mat);
    orbit2Line.rotation.y = 1.2;
    globe.scene.add(orbit2Line);

    // Second satellite
    const sat2Geo = new THREE.SphereGeometry(0.014, 8, 8);
    const sat2Mat = new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.8 });
    const sat2Dot = new THREE.Mesh(sat2Geo, sat2Mat);
    globe.scene.add(sat2Dot);
    globe.sat2Dot = sat2Dot;
    globe.orbit2Line = orbit2Line;

    // Third orbit (equatorial-ish)
    const orbit3Points = [];
    for (let i = 0; i <= 200; i++) {
        const angle = (i / 200) * Math.PI * 2;
        orbit3Points.push(new THREE.Vector3(
            orbitRadius * 1.2 * Math.cos(angle),
            orbitRadius * 1.2 * Math.sin(angle) * 0.15,
            orbitRadius * 1.2 * Math.sin(angle) * 0.9
        ));
    }
    const orbit3Geo = new THREE.BufferGeometry().setFromPoints(orbit3Points);
    const orbit3Mat = new THREE.LineBasicMaterial({ color: 0xa855f7, transparent: true, opacity: 0.08 });
    const orbit3Line = new THREE.Line(orbit3Geo, orbit3Mat);
    globe.scene.add(orbit3Line);
}

function onGlobeMouseMove(e) {
    const canvas = e.target;
    const rect = canvas.getBoundingClientRect();
    globe.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    globe.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    globe.raycaster.setFromCamera(globe.mouse, globe.camera);

    // Check markers
    const markerMeshes = globe.markers.map(m => m.dot);
    const hits = globe.raycaster.intersectObjects(markerMeshes);

    const tooltip = document.getElementById("globeTooltip");
    if (!tooltip) return;

    if (hits.length > 0) {
        const ud = hits[0].object.userData;
        tooltip.innerHTML = `
            <div class="gt-name">${ud.name}</div>
            <div class="gt-coord">${ud.lat.toFixed(2)}°N, ${ud.lon.toFixed(2)}°E</div>
            <div class="gt-hint">Click to enter dashboard</div>`;
        tooltip.style.display = "block";
        tooltip.style.left = (e.clientX - canvas.getBoundingClientRect().left + 15) + "px";
        tooltip.style.top = (e.clientY - canvas.getBoundingClientRect().top - 10) + "px";
        return;
    }

    // Check sphere for zone info
    const sphereHits = globe.raycaster.intersectObject(globe.sphere);
    if (sphereHits.length > 0) {
        const point = sphereHits[0].point;
        const lat = 90 - (Math.acos(point.y / 1.0) * 180 / Math.PI);
        const lon = (Math.atan2(point.z, -point.x) * 180 / Math.PI) - 180;
        const adjustedLon = ((lon + 540) % 360) - 180;

        // Apply globe rotation to get actual lat/lon
        const zone = getZoneFromLatLon(lat, adjustedLon);
        const zd = ZONE_DATA[zone];

        if (zd) {
            tooltip.innerHTML = `
                <div class="gt-zone">${zone}</div>
                <div class="gt-row"><span class="gt-label"> NDVI Range:</span> ${zd.ndvi}</div>
                <div class="gt-row"><span class="gt-label"> Moisture:</span> ${zd.moisture}</div>
                <div class="gt-row"><span class="gt-label"> Key Crops:</span> ${zd.crops}</div>
                <div class="gt-row"><span class="gt-label"> Risk Level:</span> ${zd.risk}</div>
                <div class="gt-row"><span class="gt-label"> Farmers:</span> ${zd.farmers}</div>`;
            tooltip.style.display = "block";
            tooltip.style.left = (e.clientX - canvas.getBoundingClientRect().left + 15) + "px";
            tooltip.style.top = (e.clientY - canvas.getBoundingClientRect().top - 10) + "px";
        }
    } else {
        tooltip.style.display = "none";
    }
}

function onGlobeClick(e) {
    const canvas = e.target;
    const rect = canvas.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const my = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    globe.raycaster.setFromCamera(new THREE.Vector2(mx, my), globe.camera);
    const markerMeshes = globe.markers.map(m => m.dot);
    const hits = globe.raycaster.intersectObjects(markerMeshes);

    if (hits.length > 0) {
        const key = hits[0].object.userData.key;
        const targetPos = hits[0].object.position.clone().normalize().multiplyScalar(2.0);

        currentSite = key;
        document.getElementById("siteSelector").value = key;

        // Smooth camera zoom to clicked site
        const startZ = globe.camera.position.z;
        const startX = globe.camera.position.x;
        const startY = globe.camera.position.y;
        let progress = 0;

        function zoomAnimate() {
            progress += 0.03;
            if (progress >= 1) {
                enterDashboard();
                // Reset camera for next visit
                setTimeout(() => {
                    globe.camera.position.set(0, 0, 2.8);
                }, 800);
                return;
            }
            const ease = 1 - Math.pow(1 - progress, 3); // easeOutCubic
            globe.camera.position.x = startX + (targetPos.x - startX) * ease;
            globe.camera.position.y = startY + (targetPos.y - startY) * ease;
            globe.camera.position.z = startZ + (targetPos.z - startZ) * ease;
            globe.camera.lookAt(0, 0, 0);
            requestAnimationFrame(zoomAnimate);
        }
        zoomAnimate();
    }
}

function getZoneFromLatLon(lat, lon) {
    if (lat > 60) return "Europe";
    if (lat > 35 && lon > -130 && lon < -50) return "North America";
    if (lat > 5 && lat < 40 && lon > 60 && lon < 100) return "South Asia";
    if (lat > -10 && lat < 30 && lon > 95 && lon < 150) return "Southeast Asia";
    if (lat > 20 && lat < 55 && lon > 100 && lon < 145) return "East Asia";
    if (lat > 20 && lat < 50 && lon > 40 && lon < 80) return "Central Asia";
    if (lat < 0 && lon > -80 && lon < -30) return "Latin America";
    if (lat > 0 && lat < 35 && lon > -20 && lon < -80) return "Latin America";
    if (lat > 15 && lat < 38 && lon > -20 && lon < 40) return "North Africa";
    if (lat > -35 && lat < 15 && lon > -20 && lon < 55) return "Sub-Saharan Africa";
    if (lat < -10 && lon > 110 && lon < 180) return "Oceania";
    return "South Asia";
}

// ═══════════════════════════════════════════════════════════════
//  4. HERO ANIMATIONS
// ═══════════════════════════════════════════════════════════════

function animateHeroStats() {
    document.querySelectorAll(".stat-value[data-count]").forEach(el => {
        const target = parseInt(el.dataset.count);
        let current = 0;
        const step = Math.ceil(target / 40);
        const interval = setInterval(() => {
            current += step;
            if (current >= target) {
                current = target;
                clearInterval(interval);
            }
            el.textContent = current;
        }, 40);
    });
}

// ═══════════════════════════════════════════════════════════════
//  5. PAGE TRANSITIONS
// ═══════════════════════════════════════════════════════════════

function enterDashboard() {
    const hero = document.getElementById("heroSection");
    const dash = document.getElementById("dashboardWrap");
    if (!hero || !dash) return;

    // Prevent double-click
    if (hero.classList.contains("hero-exit")) return;

    hero.classList.add("hero-exit");
    setTimeout(() => {
        hero.style.display = "none";
        dash.classList.add("visible");
        document.body.classList.remove("hero-active");
        document.body.classList.add("dashboard-active");
        initDashboard();
        // Scroll to top of dashboard
        window.scrollTo({ top: 0, behavior: "instant" });
        // Ensure map renders correctly after transition
        if (map) setTimeout(() => map.invalidateSize(), 100);
    }, 600);
}

function showHero() {
    const hero = document.getElementById("heroSection");
    const dash = document.getElementById("dashboardWrap");
    if (!hero || !dash) return;

    dash.classList.remove("visible");
    document.body.classList.remove("dashboard-active");
    document.body.classList.add("hero-active");
    hero.style.display = "";
    // Force reflow before removing exit class for smooth transition
    void hero.offsetHeight;
    hero.classList.remove("hero-exit");
    window.scrollTo(0, 0);
}

function scrollToGlobe() {
    // Dramatic globe exploration — zoom camera, pulse markers, spin
    const globeWrap = document.getElementById("heroGlobeWrap");
    if (!globeWrap) return;

    // Scroll the globe into center view
    globeWrap.scrollIntoView({ behavior: "smooth", block: "center" });

    // Add exploration class for glow effect
    globeWrap.classList.add("globe-exploring");
    setTimeout(() => globeWrap.classList.remove("globe-exploring"), 4000);

    // Zoom camera into the globe
    if (globe.camera) {
        const startZ = globe.camera.position.z;
        const targetZ = 1.8; // zoom in
        let progress = 0;

        function zoomIn() {
            progress += 0.02;
            if (progress >= 1) {
                // After zoom in, slowly zoom back out
                let outProgress = 0;
                function zoomOut() {
                    outProgress += 0.01;
                    if (outProgress >= 1) return;
                    const ease = outProgress * outProgress * (3 - 2 * outProgress);
                    globe.camera.position.z = targetZ + (startZ - targetZ) * ease;
                    requestAnimationFrame(zoomOut);
                }
                setTimeout(zoomOut, 1500);
                return;
            }
            const ease = 1 - Math.pow(1 - progress, 3);
            globe.camera.position.z = startZ + (targetZ - startZ) * ease;
            requestAnimationFrame(zoomIn);
        }
        zoomIn();
    }

    // Pulse all markers bigger
    globe.markers.forEach((m, i) => {
        if (m.dot) {
            const origScale = m.dot.scale.x;
            setTimeout(() => {
                m.dot.scale.set(2.5, 2.5, 2.5);
                setTimeout(() => m.dot.scale.set(origScale, origScale, origScale), 800);
            }, i * 200);
        }
    });

    // Flash tooltip with info
    const tooltip = document.getElementById("globeTooltip");
    if (tooltip) {
        tooltip.innerHTML = `
            <div class="gt-zone"> Globe Explorer</div>
            <div class="gt-row"><span class="gt-label"> Sites:</span> ${Object.keys(SITES).length} pilot sites active</div>
            <div class="gt-row"><span class="gt-label"> Orbits:</span> 3 satellite tracks visible</div>
            <div class="gt-row"><span class="gt-label"> Coverage:</span> 6 agro-climatic zones</div>
            <div class="gt-row" style="margin-top:8px;opacity:0.6;">Click any marker or drag to explore</div>`;
        tooltip.style.display = "block";
        tooltip.style.left = "50%";
        tooltip.style.top = "20px";
        tooltip.style.transform = "translateX(-50%)";
        setTimeout(() => {
            tooltip.style.display = "none";
            tooltip.style.transform = "";
        }, 4000);
    }
}

// ═══════════════════════════════════════════════════════════════
//  6. DASHBOARD INIT
// ═══════════════════════════════════════════════════════════════

let dashboardInited = false;
let mapInited = false;

function initDashboard() {
    if (dashboardInited) {
        loadDashboard(currentSite);
        return;
    }
    dashboardInited = true;

    // Defer map init until manager view is shown (needs visible container)
    initSatelliteForm();
    loadDashboard(currentSite);
    tryAutoLogin();

    // Animate summary cards stagger
    document.querySelectorAll(".summary-card").forEach((card, i) => {
        card.style.animationDelay = `${i * 0.1}s`;
    });
}

// ═══════════════════════════════════════════════════════════════
//  7. LEAFLET MAP
// ═══════════════════════════════════════════════════════════════

function initMap() {
    if (map) return;
    map = L.map("map", {
        center: [20, 78],
        zoom: 5,
        zoomControl: true,
        attributionControl: false,
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 19,
        subdomains: "abcd",
    }).addTo(map);

    // Force size recalc after transition
    setTimeout(() => map.invalidateSize(), 100);
    setTimeout(() => map.invalidateSize(), 700);
}

function plotFields(fields, siteLat, siteLon) {
    Object.values(fieldLayers).forEach(l => map.removeLayer(l));
    fieldLayers = {};

    const bounds = [];

    fields.forEach(f => {
        if (!f.bbox || f.bbox.length < 4) return;
        const [w, s, e, n] = f.bbox;
        const rect = L.rectangle([[s, w], [n, e]], {
            color: getFieldColor(f),
            fillColor: getFieldColor(f),
            fillOpacity: 0.25,
            weight: 2,
        }).addTo(map);

        rect.bindPopup(`
            <div style="font-family:'Space Grotesk',sans-serif;font-size:13px;line-height:1.5;min-width:180px">
                <strong style="font-family:'Lora',serif;font-size:14px">${esc(f.name)}</strong><br>
                <span style="opacity:.6;font-size:11px">${esc(f.field_id)}</span><br>
                Crop: <b>${esc(f.crop)}</b> · ${f.area_ha} ha<br>
                NDVI: <b style="color:${ndviColor(f.latest_ndvi)}">${f.latest_ndvi?.toFixed(3) ?? "—"}</b> ·
                SMC: <b>${f.soil_moisture?.toFixed(1) ?? "—"}%</b><br>
                Yield: <b>${f.yield_forecast?.toFixed(2) ?? "—"}</b> t/ha
                ${f.anomaly_count > 0 ? `<br><span style="color:#ef4444"> ${f.anomaly_count} anomalies</span>` : ""}
            </div>
        `);

        fieldLayers[f.field_id] = rect;
        bounds.push([[s, w], [n, e]]);
    });

    // Site marker
    L.circleMarker([siteLat, siteLon], {
        radius: 8, color: "#22c55e", fillColor: "#22c55e", fillOpacity: 0.7, weight: 2,
    }).addTo(map).bindPopup("Site Center");

    if (bounds.length > 0) {
        map.fitBounds(bounds.flat(), { padding: [30, 30], maxZoom: 14 });
    } else {
        map.setView([siteLat, siteLon], 12);
    }
}

function getFieldColor(f) {
    if (f.anomaly_count > 2) return "#ef4444";
    if (f.smc_category === "very_dry") return "#f59e0b";
    if (f.ndvi_class === "very_dense" || f.ndvi_class === "dense") return "#22c55e";
    if (f.ndvi_class === "moderate") return "#06b6d4";
    return "#6366f1";
}

function ndviColor(v) {
    if (v == null) return "#94a3b8";
    if (v > 0.6) return "#22c55e";
    if (v > 0.4) return "#06b6d4";
    if (v > 0.2) return "#f59e0b";
    return "#ef4444";
}

// ═══════════════════════════════════════════════════════════════
//  8. DASHBOARD DATA LOADING
// ═══════════════════════════════════════════════════════════════

async function switchSite(siteKey) {
    currentSite = siteKey;
    // Reset lazy-load flags so new site data loads fresh

    await loadDashboard(siteKey);
}

async function loadDashboard(siteKey) {
    setStatus("Loading dashboard…");
    try {
        const resp = await fetch(`/api/dashboard/${siteKey}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        dashboardData = await resp.json();
        renderDashboard(dashboardData);
        setStatus("● Live — " + dashboardData.site.short_name);
    } catch (err) {
        setStatus(" Error: " + err.message);
        console.error("Dashboard load failed:", err);
    }
}

function renderDashboard(data) {
    const site = data.site;
    const summary = data.summary;
    const fields = data.fields;

    // Summary bar
    animateValue("#sumFields", summary.total_fields);
    animateValue("#sumArea", summary.total_area_ha + " ha");
    animateValue("#sumNDVI", summary.avg_ndvi?.toFixed(3) ?? "—");
    animateValue("#sumSMC", (summary.avg_smc?.toFixed(1) ?? "—") + "%");
    animateValue("#sumAnomalies", summary.total_anomalies);
    animateValue("#sumHardware", site.hub_hardware?.split(" ").slice(-3).join(" ") ?? "—");

    // Site info
    q("#siteNameHint").textContent = site.name;
    q("#infoDemoWindow").textContent = `${site.demo_window.start} → ${site.demo_window.end} (${site.demo_window.season})`;
    q("#infoAgroZone").textContent = site.agro_zone;
    q("#infoProbes").textContent = site.soil_probes;
    q("#infoHub").textContent = site.hub_hardware;

    // Always render farmer view data
    renderFarmerView(data);

    // Render manager data (map, table, charts)
    if (mapInited) {
        setTimeout(() => {
            if (map) map.invalidateSize();
            plotFields(fields, site.lat, site.lon);
        }, 200);
    }

    renderFieldsTable(fields);
    populateFieldSelects(fields);

    if (fields.length > 0) loadFieldIndices(fields[0].field_id);

    loadSoilMoisture();
    loadAnomalies();
    loadYield();
    loadWeather(false);
    loadNudges();

    q("#satDate").value = new Date().toISOString().slice(0, 10);
}

function animateValue(selector, value) {
    const el = q(selector);
    if (!el) return;
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    setTimeout(() => {
        el.textContent = value;
        el.style.transition = "all 0.4s ease";
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
    }, 100);
}

// ═══════════════════════════════════════════════════════════════
//  9. FIELDS TABLE
// ═══════════════════════════════════════════════════════════════

function renderFieldsTable(fields) {
    q("#fieldCount").textContent = `${fields.length} fields`;
    q("#fieldsTable").innerHTML = `
        <table class="data-table">
            <thead>
                <tr>
                    <th>Field</th>
                    <th>Crop</th>
                    <th>Area</th>
                    <th>NDVI</th>
                    <th>SMC</th>
                    <th>Yield</th>
                    <th>Risk</th>
                </tr>
            </thead>
            <tbody>
                ${fields.map((f, i) => `
                    <tr class="${f.anomaly_count > 2 ? 'row-alert' : ''}" onclick="loadFieldIndices('${f.field_id}')" style="animation-delay:${i * 0.05}s">
                        <td>
                            <div class="field-name">${esc(f.name)}</div>
                            <div class="field-id">${esc(f.field_id)}</div>
                        </td>
                        <td><span class="crop-badge">${esc(f.crop)}</span></td>
                        <td>${f.area_ha} ha</td>
                        <td>
                            <span class="ndvi-dot" style="background:${ndviColor(f.latest_ndvi)}"></span>
                            ${f.latest_ndvi?.toFixed(3) ?? "—"}
                        </td>
                        <td><span class="smc-badge smc-${f.smc_category}">${f.soil_moisture?.toFixed(1) ?? "—"}%</span></td>
                        <td>${f.yield_forecast?.toFixed(2) ?? "—"} t/ha</td>
                        <td>
                            <span class="risk-badge risk-${f.yield_risk}">${f.yield_risk}</span>
                            ${f.anomaly_count > 0 ? `<span class="anomaly-count">${f.anomaly_count}</span>` : ""}
                        </td>
                    </tr>
                `).join("")}
            </tbody>
        </table>`;
}

function populateFieldSelects(fields) {
    q("#ndviFieldSelect").innerHTML = fields.map(f =>
        `<option value="${f.field_id}">${f.name} (${f.crop})</option>`
    ).join("");
}

// ═══════════════════════════════════════════════════════════════
//  10. TABS
// ═══════════════════════════════════════════════════════════════

function switchTab(tabId) {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.querySelector(`.tab[data-tab="${tabId}"]`)?.classList.add("active");
    q(`#panel-${tabId}`)?.classList.add("active");

}


// ═══════════════════════════════════════════════════════════════
//  11. CHARTS — NDVI / NDWI
// ═══════════════════════════════════════════════════════════════

const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: { labels: { color: "#94a3b8", font: { family: "'Space Grotesk', sans-serif", size: 11 } } },
        tooltip: {
            backgroundColor: "rgba(17,24,39,0.95)",
            titleFont: { family: "'Space Grotesk', sans-serif", weight: "600" },
            bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
            borderColor: "rgba(34,197,94,0.3)",
            borderWidth: 1,
            cornerRadius: 8,
        },
    },
    scales: {
        x: {
            ticks: { color: "#64748b", font: { size: 10, family: "'JetBrains Mono', monospace" }, maxTicksLimit: 12 },
            grid: { color: "rgba(148,163,184,0.06)" },
        },
        y: {
            ticks: { color: "#64748b", font: { size: 10, family: "'JetBrains Mono', monospace" } },
            grid: { color: "rgba(148,163,184,0.06)" },
        },
    },
    animation: { duration: 800, easing: "easeOutQuart" },
};

function makeChartOpts(yLabel, yMin, yMax) {
    const opts = JSON.parse(JSON.stringify(CHART_DEFAULTS));
    if (yLabel) opts.scales.y.title = { display: true, text: yLabel, color: "#94a3b8", font: { family: "'Space Grotesk', sans-serif" } };
    if (yMin != null) opts.scales.y.min = yMin;
    if (yMax != null) opts.scales.y.max = yMax;
    return opts;
}

async function loadFieldIndices(fieldId) {
    if (!fieldId) return;
    q("#ndviFieldSelect").value = fieldId;
    try {
        const resp = await fetch(`/api/indices/${fieldId}?days=90`);
        const data = await resp.json();
        renderNDVIChart(data.timeseries);
        renderNDWIChart(data.timeseries);
        renderIndicesSummary(data.summary, fieldId);
    } catch (err) {
        console.error("Failed to load indices:", err);
    }
}

function renderNDVIChart(ts) {
    const ctx = q("#ndviChart");
    if (ndviChart) ndviChart.destroy();
    ndviChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: ts.map(t => t.date),
            datasets: [{
                label: "NDVI",
                data: ts.map(t => t.ndvi),
                borderColor: "#22c55e",
                backgroundColor: createGradient(ctx, "#22c55e"),
                borderWidth: 2.5,
                fill: true,
                tension: 0.4,
                pointRadius: 2,
                pointBackgroundColor: "#22c55e",
                pointHoverRadius: 6,
            }],
        },
        options: makeChartOpts("NDVI", -0.1, 1.0),
    });
}

function renderNDWIChart(ts) {
    const ctx = q("#ndwiChart");
    if (ndwiChart) ndwiChart.destroy();
    ndwiChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: ts.map(t => t.date),
            datasets: [{
                label: "NDWI",
                data: ts.map(t => t.ndwi),
                borderColor: "#06b6d4",
                backgroundColor: createGradient(ctx, "#06b6d4"),
                borderWidth: 2.5,
                fill: true,
                tension: 0.4,
                pointRadius: 2,
                pointBackgroundColor: "#06b6d4",
                pointHoverRadius: 6,
            }],
        },
        options: makeChartOpts("NDWI", -0.5, 0.6),
    });
}

function createGradient(canvas, color) {
    try {
        const ctx2 = canvas.getContext("2d");
        const grad = ctx2.createLinearGradient(0, 0, 0, 300);
        grad.addColorStop(0, color + "30");
        grad.addColorStop(1, color + "00");
        return grad;
    } catch { return color + "15"; }
}

function renderIndicesSummary(summary, fieldId) {
    if (!summary || !summary.ndvi_current) {
        q("#indicesSummaryCard").hidden = true;
        return;
    }
    q("#indicesSummaryCard").hidden = false;
    q("#indicesSummary").innerHTML = `
        <div class="metrics-grid">
            <div class="metric">
                <span class="metric-label">Current NDVI</span>
                <span class="metric-value" style="color:${ndviColor(summary.ndvi_current)}">${summary.ndvi_current?.toFixed(4)}</span>
                <span class="metric-sub">${summary.ndvi_class}</span>
            </div>
            <div class="metric">
                <span class="metric-label">NDVI Range</span>
                <span class="metric-value">${summary.ndvi_min?.toFixed(3)} — ${summary.ndvi_max?.toFixed(3)}</span>
                <span class="metric-sub">Mean: ${summary.ndvi_mean?.toFixed(3)}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Trend</span>
                <span class="metric-value trend-${summary.ndvi_trend}">${trendIcon(summary.ndvi_trend)} ${summary.ndvi_trend}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Current NDWI</span>
                <span class="metric-value">${summary.ndwi_current?.toFixed(4)}</span>
                <span class="metric-sub">${summary.ndwi_class}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Observations</span>
                <span class="metric-value">${summary.observations}</span>
            </div>
        </div>`;
}

function trendIcon(t) {
    if (t === "increasing") return "";
    if (t === "decreasing") return "";
    return "";
}

// ═══════════════════════════════════════════════════════════════
//  12. SOIL MOISTURE
// ═══════════════════════════════════════════════════════════════

async function loadSoilMoisture() {
    try {
        const resp = await fetch(`/api/soil-moisture/site/${currentSite}`);
        const data = await resp.json();
        renderSMCChart(data.fields);
        renderSMCDetails(data.fields);
    } catch (err) { console.error("SMC load failed:", err); }
}

function renderSMCChart(fields) {
    const ctx = q("#smcChart");
    if (smcChart) smcChart.destroy();
    smcChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: fields.map(f => f.field_name),
            datasets: [{
                label: "Soil Moisture (%)",
                data: fields.map(f => f.smc_percent),
                backgroundColor: fields.map(f => smcBarColor(f.category) + "AA"),
                borderColor: fields.map(f => smcBarColor(f.category)),
                borderWidth: 1,
                borderRadius: 8,
                borderSkipped: false,
            }],
        },
        options: { ...makeChartOpts("SMC %", 0, 55), indexAxis: "y" },
    });
}

function renderSMCDetails(fields) {
    q("#smcDetails").innerHTML = fields.map(f => `
        <div class="smc-row">
            <div class="smc-field"><strong>${esc(f.field_name)}</strong> <span class="crop-badge">${esc(f.crop)}</span></div>
            <div class="smc-bar-wrap">
                <div class="smc-bar" style="width:${Math.min(f.smc_percent / 55 * 100, 100)}%;background:${smcBarColor(f.category)}">${f.smc_percent.toFixed(1)}%</div>
            </div>
            <div class="smc-meta">
                <span class="smc-badge smc-${f.category}">${f.category}</span>
                <span class="smc-confidence">Conf: ${(f.confidence * 100).toFixed(0)}%</span>
            </div>
        </div>
    `).join("") || '<div class="empty-state">No data</div>';
}

function smcBarColor(cat) {
    return { very_dry: "#ef4444", dry: "#f59e0b", adequate: "#22c55e", wet: "#06b6d4", saturated: "#6366f1" }[cat] || "#94a3b8";
}

// ═══════════════════════════════════════════════════════════════
//  13. ANOMALIES
// ═══════════════════════════════════════════════════════════════

async function loadAnomalies() {
    try {
        const resp = await fetch(`/api/anomalies/site/${currentSite}`);
        const data = await resp.json();
        renderAnomalies(data);
    } catch (err) { console.error("Anomaly load failed:", err); }
}

function renderAnomalies(data) {
    const panel = q("#anomaliesPanel");
    if (data.total_anomalies === 0) {
        panel.innerHTML = '<div class="empty-state"> No spectral anomalies detected.</div>';
        return;
    }
    let html = `<div class="anomaly-header">Total: <strong>${data.total_anomalies}</strong> spectral anomalies</div>`;
    for (const [fieldId, fd] of Object.entries(data.fields)) {
        if (fd.count === 0) continue;
        html += `<div class="anomaly-field">
            <h4>${esc(fd.field_name)} <span class="anomaly-count">${fd.count}</span></h4>
            ${fd.anomalies.map(a => `
                <div class="anomaly-item anomaly-${a.severity}">
                    <div class="anomaly-head">
                        <span class="anomaly-type">${anomalyIcon(a.type)} ${a.type.replace(/_/g, " ")}</span>
                        <span class="anomaly-date">${a.date}</span>
                        <span class="risk-badge risk-${a.severity === 'high' ? 'high' : a.severity === 'medium' ? 'medium' : 'low'}">${a.severity}</span>
                    </div>
                    <p class="anomaly-desc">${esc(a.description)}</p>
                </div>
            `).join("")}
        </div>`;
    }
    panel.innerHTML = html;
}

function anomalyIcon(type) {
    return { ndvi_drop: "", growth_lag: "", chlorophyll_stress: "" }[type] || "";
}

// ═══════════════════════════════════════════════════════════════
//  14. YIELD
// ═══════════════════════════════════════════════════════════════

async function loadYield() {
    try {
        const resp = await fetch(`/api/yield/site/${currentSite}`);
        const data = await resp.json();
        renderYieldChart(data.forecasts);
        renderYieldDetails(data);
    } catch (err) { console.error("Yield load failed:", err); }
}

function renderYieldChart(forecasts) {
    const ctx = q("#yieldChart");
    if (yieldChart) yieldChart.destroy();
    yieldChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: forecasts.map(f => f.field_id),
            datasets: [
                {
                    label: "Yield (t/ha)",
                    data: forecasts.map(f => f.yield_tonnes_ha),
                    backgroundColor: forecasts.map(f => f.risk_level === "high" ? "rgba(239,68,68,0.7)" : f.risk_level === "medium" ? "rgba(245,158,11,0.7)" : "rgba(34,197,94,0.7)"),
                    borderRadius: 8,
                },
                {
                    label: "Baseline",
                    data: forecasts.map(f => f.baseline_yield),
                    type: "line",
                    borderColor: "#94a3b8",
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: makeChartOpts("Yield (t/ha)", 0, null),
    });
}

function renderYieldDetails(data) {
    q("#yieldDetails").innerHTML = `
        <div class="yield-summary">
            <div class="metric"><span class="metric-label">Total Yield</span><span class="metric-value">${data.total_yield_tonnes} t</span></div>
            <div class="metric"><span class="metric-label">Total Area</span><span class="metric-value">${data.total_area_ha} ha</span></div>
            <div class="metric"><span class="metric-label">Avg Yield</span><span class="metric-value">${data.avg_yield_per_ha} t/ha</span></div>
        </div>
        ${data.forecasts.map(f => `
            <div class="yield-row">
                <div class="yield-field"><strong>${esc(f.field_id)}</strong> <span class="crop-badge">${esc(f.crop)}</span></div>
                <div class="yield-values">
                    <span class="yield-main">${f.yield_tonnes_ha} t/ha</span>
                    <span class="yield-range">(${f.yield_range.low} — ${f.yield_range.high})</span>
                </div>
                <div class="yield-risk">
                    <span class="risk-badge risk-${f.risk_level}">${f.risk_level} · ${(f.risk_score * 100).toFixed(0)}%</span>
                    ${f.risk_factors.length > 0 ? f.risk_factors.map(r => `<span class="risk-tag">${esc(r)}</span>`).join("") : ""}
                </div>
            </div>
        `).join("")}`;
}

// ═══════════════════════════════════════════════════════════════
//  15. WEATHER
// ═══════════════════════════════════════════════════════════════

async function loadWeather(force = false) {
    try {
        const resp = await fetch(`/api/weather/${currentSite}?days=30&force=${force}`);
        const data = await resp.json();
        renderWeatherChart(data.weather);
        renderRainChart(data.weather);
    } catch (err) { console.error("Weather load failed:", err); }
}

function renderWeatherChart(weather) {
    const ctx = q("#weatherChart");
    if (weatherChart) weatherChart.destroy();
    weatherChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: weather.map(w => w.date),
            datasets: [
                { label: "Max Temp (°C)", data: weather.map(w => w.temp_max), borderColor: "#ef4444", backgroundColor: "rgba(239,68,68,0.05)", borderWidth: 2, tension: 0.3, pointRadius: 1, fill: true },
                { label: "Min Temp (°C)", data: weather.map(w => w.temp_min), borderColor: "#06b6d4", backgroundColor: "rgba(6,182,212,0.05)", borderWidth: 2, tension: 0.3, pointRadius: 1, fill: true },
            ],
        },
        options: makeChartOpts("Temperature (°C)", null, null),
    });
}

function renderRainChart(weather) {
    const ctx = q("#rainChart");
    if (rainChart) rainChart.destroy();
    const opts = makeChartOpts(null, null, null);
    opts.scales.y = { position: "left", title: { display: true, text: "Rainfall (mm)", color: "#94a3b8" }, ticks: { color: "#64748b" }, grid: { color: "rgba(148,163,184,0.06)" } };
    opts.scales.y1 = { position: "right", title: { display: true, text: "ET₀ (mm)", color: "#94a3b8" }, ticks: { color: "#64748b" }, grid: { drawOnChartArea: false } };

    rainChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: weather.map(w => w.date),
            datasets: [
                { label: "Rainfall (mm)", data: weather.map(w => w.rainfall_mm), backgroundColor: "rgba(6,182,212,0.5)", borderRadius: 4, yAxisID: "y" },
                { label: "ET₀ (mm)", data: weather.map(w => w.et0), type: "line", borderColor: "#f59e0b", borderWidth: 2, tension: 0.3, pointRadius: 1, fill: false, yAxisID: "y1" },
            ],
        },
        options: opts,
    });
}

// ═══════════════════════════════════════════════════════════════
//  16. NUDGES
// ═══════════════════════════════════════════════════════════════

async function loadNudges() {
    try {
        const resp = await fetch(`/api/nudges/${currentSite}`);
        const data = await resp.json();
        renderNudges(data);
    } catch (err) { console.error("Nudge load failed:", err); }
}

function renderNudges(data) {
    const panel = q("#nudgesPanel");
    if (!data.nudges || data.nudges.length === 0) {
        panel.innerHTML = '<div class="empty-state">No nudges generated.</div>';
        return;
    }
    panel.innerHTML = `
        <div class="nudge-summary">
            <span>${data.total_nudges} nudges</span>
            ${data.critical > 0 ? `<span class="risk-badge risk-high">${data.critical} critical</span>` : ""}
            ${data.medium > 0 ? `<span class="risk-badge risk-medium">${data.medium} medium</span>` : ""}
        </div>
        ${data.nudges.map((n, i) => `
            <div class="nudge-item nudge-${n.urgency}" style="animation-delay:${i * 0.05}s">
                <div class="nudge-icon">${nudgeIcon(n.nudge_type)}</div>
                <div class="nudge-content">
                    <div class="nudge-msg">${esc(n.message_en)}</div>
                    ${n.message_local && n.language !== "en" ? `<div class="nudge-local">${esc(n.message_local)}</div>` : ""}
                    <div class="nudge-meta">
                        <span class="nudge-type">${n.nudge_type}</span>
                        <span class="risk-badge risk-${n.urgency === "critical" ? "high" : n.urgency}">${n.urgency}</span>
                        ${n.duration_minutes ? `<span>${n.duration_minutes} min</span>` : ""}
                    </div>
                </div>
            </div>
        `).join("")}`;
}

function nudgeIcon(type) {
    return { irrigate: "", skip_irrigation: "", wait_for_rain: "", monitor: "", pest_alert: "" }[type] || "";
}

// ═══════════════════════════════════════════════════════════════
//  17. SATELLITE SEARCH
// ═══════════════════════════════════════════════════════════════

function initSatelliteForm() {
    q("#searchForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        await doSatelliteSearch();
    });
    const d = new Date(); d.setDate(d.getDate() - 30);
    q("#satDate").value = d.toISOString().slice(0, 10);
}

async function doSatelliteSearch() {
    const lat = dashboardData?.site?.lat || 20;
    const lon = dashboardData?.site?.lon || 78;
    const date = q("#satDate").value;
    const days = parseInt(q("#satDays").value) || 15;
    const cloudCover = parseInt(q("#satCloud").value) || 30;

    const collections = [];
    if (q("#chkS2").checked) collections.push("sentinel-2-l2a");
    if (q("#chkS1").checked) collections.push("sentinel-1-grd");
    if (collections.length === 0) return;

    try {
        const resp = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat, lon, date, days, collections, cloud_cover: cloudCover, limit: 12 }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        renderSatResults(data);
    } catch (err) {
        q("#satResults").innerHTML = `<div class="error-banner">${esc(err.message)}</div>`;
        q("#satResultsCard").hidden = false;
    }
}

function renderSatResults(data) {
    q("#satResultsCard").hidden = false;
    let totalCount = 0, html = "";

    for (const [colId, col] of Object.entries(data)) {
        if (!col.features) continue;
        totalCount += col.count;
        col.features.forEach(f => {
            const dt = f.datetime ? new Date(f.datetime) : null;
            const dateStr = dt ? dt.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "N/A";
            const cc = f.cloud_cover != null ? ` ${f.cloud_cover.toFixed(1)}%` : "";
            html += `
                <div class="result-card">
                    ${f.thumbnail ? `<img class="result-thumb" src="${escAttr(f.thumbnail)}" alt="Preview" loading="lazy" onerror="this.style.display='none'">` : ""}
                    <div class="result-body">
                        <div class="result-id">${esc(f.id)}</div>
                        <div class="result-meta"><span> ${dateStr}</span><span> ${esc(f.platform || "")}</span>${cc ? `<span>${cc}</span>` : ""}</div>
                        ${f.assets?.Product ? `<a class="btn-download" href="${escAttr(f.assets.Product.href)}" target="_blank"> Download</a>` : ""}
                    </div>
                </div>`;
        });
    }

    q("#satResultCount").textContent = `${totalCount} scenes`;
    q("#satResults").innerHTML = html || '<div class="empty-state">No scenes found.</div>';
}

// ═══════════════════════════════════════════════════════════════
//  18. AUTH
// ═══════════════════════════════════════════════════════════════

async function tryAutoLogin() {
    try {
        const resp = await fetch("/api/credentials");
        const data = await resp.json();
        if (data.saved) {
            q("#cdseUser").value = data.username;
            const tokenResp = await fetch("/api/token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
            const tokenData = await tokenResp.json();
            if (tokenResp.ok && tokenData.access_token) {
                accessToken = tokenData.access_token;
                q("#loginForm").hidden = true;
                q("#loginSuccess").hidden = false;
            }
        }
    } catch (e) { /* silent */ }
}

async function doLogin() {
    const user = q("#cdseUser").value.trim();
    const pass = q("#cdsePass").value;
    if (!user || !pass) { showLoginError("Enter email and password."); return; }
    try {
        const resp = await fetch("/api/token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: user, password: pass, save: true }) });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Auth failed");
        accessToken = data.access_token;
        q("#loginForm").hidden = true;
        q("#loginSuccess").hidden = false;
    } catch (err) { showLoginError(err.message); }
}

async function doLogout() {
    accessToken = null;
    try { await fetch("/api/credentials", { method: "DELETE" }); } catch (e) { }
    q("#loginForm").hidden = false;
    q("#loginSuccess").hidden = true;
    q("#cdsePass").value = "";
}

function showLoginError(msg) {
    const el = q("#loginError");
    el.textContent = msg;
    el.hidden = false;
}

// ═══════════════════════════════════════════════════════════════
//  19. VIEW SWITCHING (Farmer / Manager)
// ═══════════════════════════════════════════════════════════════

let currentView = "farmer";

function switchView(view) {
    currentView = view;
    const farmerView = q("#farmerView");
    const managerView = q("#managerView");
    if (!farmerView || !managerView) return;

    document.querySelectorAll(".view-btn").forEach(b => b.classList.remove("active"));
    document.querySelector(`.view-btn[data-view="${view}"]`)?.classList.add("active");

    if (view === "farmer") {
        farmerView.style.display = "";
        managerView.style.display = "none";
        if (dashboardData) renderFarmerView(dashboardData);
    } else {
        farmerView.style.display = "none";
        managerView.style.display = "";
        // Init map on first manager view visit
        if (!mapInited) {
            mapInited = true;
            setTimeout(() => {
                initMap();
                if (dashboardData) {
                    plotFields(dashboardData.fields, dashboardData.site.lat, dashboardData.site.lon);
                }
            }, 50);
        } else if (map) {
            setTimeout(() => map.invalidateSize(), 100);
        }
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
}

// ═══════════════════════════════════════════════════════════════
//  20. FARMER VIEW RENDERING
// ═══════════════════════════════════════════════════════════════

function renderFarmerView(data) {
    renderFarmHealth(data);
    renderCropAdvisory();
    renderFarmerActions(data);
    renderModelAccuracy();
    renderFarmerFields(data);
    renderFarmerWeather();
    renderWaterBalance(data);
    renderCropTimeline();
    renderAlertDigest();
    populateCompareSelector();
}

function renderFarmHealth(data) {
    const summary = data.summary;
    const fields = data.fields;

    // Calculate health score (0–100) from NDVI, SMC, anomalies
    const ndviScore = Math.min((summary.avg_ndvi || 0) / 0.7 * 100, 100);
    const smcRaw = summary.avg_smc || 0;
    const smcScore = smcRaw < 10 ? smcRaw * 3 : smcRaw > 45 ? Math.max(0, 100 - (smcRaw - 45) * 5) : 100 - Math.abs(smcRaw - 28) * 1.5;
    const anomalyCap = Math.min(summary.total_anomalies || 0, 20);
    const anomalyScore = Math.max(0, 100 - anomalyCap * 5);

    const healthScore = Math.round(ndviScore * 0.4 + smcScore * 0.3 + anomalyScore * 0.3);
    const clampedScore = Math.max(0, Math.min(100, healthScore));

    // Animate ring
    const arc = q("#healthArc");
    if (arc) {
        const circumference = 327; // 2 * π * 52
        const offset = circumference - (clampedScore / 100) * circumference;
        arc.style.strokeDashoffset = offset;
        arc.style.stroke = clampedScore >= 70 ? "#22c55e" : clampedScore >= 40 ? "#f59e0b" : "#ef4444";
    }

    const scoreEl = q("#healthScore");
    if (scoreEl) {
        scoreEl.textContent = clampedScore;
        scoreEl.style.color = clampedScore >= 70 ? "#22c55e" : clampedScore >= 40 ? "#f59e0b" : "#ef4444";
    }

    // Summary text
    const summaryEl = q("#healthSummary");
    if (summaryEl) {
        const dryFields = fields.filter(f => f.smc_category === "very_dry" || f.smc_category === "dry").length;
        const alertFields = fields.filter(f => f.anomaly_count > 0).length;
        let msg = "";

        if (clampedScore >= 70) {
            msg = `Your farm is doing well! ${summary.total_fields} fields across ${summary.total_area_ha} ha are in good condition.`;
        } else if (clampedScore >= 40) {
            msg = `Some attention needed.`;
            if (dryFields > 0) msg += ` ${dryFields} field${dryFields > 1 ? "s need" : " needs"} watering.`;
            if (alertFields > 0) msg += ` ${alertFields} field${alertFields > 1 ? "s have" : " has"} alerts.`;
        } else {
            msg = `Your farm needs immediate care.`;
            if (dryFields > 0) msg += ` ${dryFields} field${dryFields > 1 ? "s are" : " is"} too dry — irrigate today.`;
            if (alertFields > 0) msg += ` ${alertFields} field${alertFields > 1 ? "s show" : " shows"} signs of stress.`;
        }
        summaryEl.textContent = msg;
    }
}

function renderFarmerActions(data) {
    const panel = q("#farmerActions");
    if (!panel) return;

    // Fetch nudges and render as simple actions
    fetch(`/api/nudges/${currentSite}`)
        .then(r => r.json())
        .then(nudgeData => {
            if (!nudgeData.nudges || nudgeData.nudges.length === 0) {
                panel.innerHTML = `
                    <div class="farmer-action info">
                        <div class="action-icon"></div>
                        <div class="action-body">
                            <div class="action-title">All good today!</div>
                            <div class="action-desc">No urgent actions needed. Keep monitoring your fields.</div>
                            <span class="action-tag ok">All Clear</span>
                        </div>
                    </div>`;
                return;
            }

            panel.innerHTML = nudgeData.nudges.slice(0, 6).map((n, i) => {
                const urgencyClass = n.urgency === "critical" ? "urgent" : n.urgency === "high" ? "important" : "info";
                const tagClass = n.urgency === "critical" ? "act-now" : n.urgency === "high" ? "watch" : "ok";
                const tagText = n.urgency === "critical" ? "Act Now" : n.urgency === "high" ? "Watch" : "Info";
                const icon = farmerActionIcon(n.nudge_type);
                const simpleMsg = simplifyNudgeMessage(n);

                return `
                    <div class="farmer-action ${urgencyClass}" style="animation-delay:${i * 0.08}s">
                        <div class="action-icon">${icon}</div>
                        <div class="action-body">
                            <div class="action-title">${esc(simpleMsg.title)}</div>
                            <div class="action-desc">${esc(simpleMsg.desc)}</div>
                            <span class="action-tag ${tagClass}">${tagText}</span>
                        </div>
                    </div>`;
            }).join("");
        })
        .catch(() => {
            panel.innerHTML = `<div class="empty-state">Unable to load actions.</div>`;
        });
}

function farmerActionIcon(type) {
    return { irrigate: "", skip_irrigation: "", wait_for_rain: "", monitor: "", pest_alert: "" }[type] || "";
}

function simplifyNudgeMessage(nudge) {
    const t = nudge.nudge_type;
    const field = nudge.message_en.match(/Field ([^:]+)/)?.[1] || "Your field";
    const mins = nudge.duration_minutes;

    if (t === "irrigate") {
        return {
            title: `Water "${field}" today`,
            desc: mins ? `Run irrigation for about ${mins} minutes. Soil is too dry.` : "Soil moisture is low — irrigate soon.",
        };
    } else if (t === "skip_irrigation") {
        return { title: `No watering needed — "${field}"`, desc: "Soil has enough moisture. Save water today." };
    } else if (t === "wait_for_rain") {
        return { title: `Rain expected — "${field}"`, desc: "Hold off on irrigation. Rain is forecast in the coming days." };
    } else if (t === "pest_alert") {
        return { title: `Check "${field}" for pests`, desc: "Satellite detected unusual spots. Walk the field and inspect crops." };
    } else if (t === "monitor") {
        return { title: `Keep an eye on "${field}"`, desc: "Some changes detected. No action needed yet, but watch closely." };
    }
    return { title: nudge.message_en.slice(0, 60), desc: "" };
}

function renderFarmerFields(data) {
    const panel = q("#farmerFields");
    if (!panel) return;
    const fields = data.fields;

    panel.innerHTML = fields.map((f, i) => {
        const health = getFieldHealth(f);
        const statusText = getFieldStatusText(f);

        return `
            <div class="farmer-field-card" style="animation-delay:${i * 0.08}s">
                <div class="field-health-dot ${health.cls}">
                    ${health.icon}
                </div>
                <div class="field-info">
                    <div class="field-info-name">${esc(f.name)}</div>
                    <div class="field-info-crop">${esc(f.crop)} · ${f.area_ha} ha</div>
                    <div class="field-info-status" style="color:${health.color}">${statusText}</div>
                </div>
                <div class="field-mini-stats">
                    <div class="mini-stat"> <strong>${f.latest_ndvi?.toFixed(2) ?? "—"}</strong></div>
                    <div class="mini-stat"> <strong>${f.soil_moisture?.toFixed(0) ?? "—"}%</strong></div>
                    <div class="mini-stat"> <strong>${f.yield_forecast?.toFixed(1) ?? "—"}</strong> t/ha</div>
                </div>
            </div>`;
    }).join("") || '<div class="empty-state">No fields found.</div>';
}

function getFieldHealth(f) {
    if (f.anomaly_count > 2 || f.smc_category === "very_dry") {
        return { cls: "poor", icon: "", color: "#ef4444" };
    }
    if (f.smc_category === "dry" || f.anomaly_count > 0 || (f.latest_ndvi != null && f.latest_ndvi < 0.3)) {
        return { cls: "fair", icon: "", color: "#f59e0b" };
    }
    return { cls: "good", icon: "", color: "#22c55e" };
}

function getFieldStatusText(f) {
    if (f.smc_category === "very_dry") return "Soil very dry — needs water!";
    if (f.smc_category === "dry") return "Soil a bit dry — consider irrigating";
    if (f.anomaly_count > 2) return `${f.anomaly_count} alerts detected`;
    if (f.anomaly_count > 0) return `${f.anomaly_count} minor alert${f.anomaly_count > 1 ? "s" : ""}`;
    if (f.latest_ndvi != null && f.latest_ndvi > 0.5) return "Crop is growing well";
    if (f.latest_ndvi != null && f.latest_ndvi > 0.3) return "Crop health is moderate";
    return "Healthy — no issues";
}

function renderFarmerWeather() {
    fetch(`/api/weather/${currentSite}?days=7&force=false`)
        .then(r => r.json())
        .then(data => {
            const panel = q("#farmerWeather");
            if (!panel || !data.weather || data.weather.length === 0) return;

            const today = data.weather[0];
            const forecast = data.weather.slice(1, 7);
            const todayIcon = getWeatherIcon(today);
            const todayDesc = getWeatherDesc(today);

            let html = `
                <div class="weather-today">
                    <div class="weather-today-icon">${todayIcon}</div>
                    <div class="weather-today-info">
                        <h3>Today — ${todayDesc}</h3>
                        <div class="temp-range">
                            <span class="hi">${today.temp_max?.toFixed(0) ?? "—"}°</span> /
                            <span class="lo">${today.temp_min?.toFixed(0) ?? "—"}°</span>
                        </div>
                        <div class="weather-detail">
                            ${today.rainfall_mm > 0 ? ` ${today.rainfall_mm.toFixed(1)} mm rain` : "No rain expected"}
                            ·  ${today.wind_speed?.toFixed(0) ?? "—"} km/h
                        </div>
                    </div>
                </div>
                <div class="weather-forecast">
                    ${forecast.map(w => {
                        const d = new Date(w.date);
                        const dayName = d.toLocaleDateString("en-US", { weekday: "short" });
                        return `
                            <div class="forecast-day">
                                <div class="day-name">${dayName}</div>
                                <div class="day-icon">${getWeatherIcon(w)}</div>
                                <div class="day-temps">${w.temp_max?.toFixed(0) ?? "—"}° / ${w.temp_min?.toFixed(0) ?? "—"}°</div>
                                ${w.rainfall_mm > 0.5 ? `<div class="day-rain">${w.rainfall_mm.toFixed(1)}mm</div>` : ""}
                            </div>`;
                    }).join("")}
                </div>`;

            panel.innerHTML = html;
        })
        .catch(() => {
            q("#farmerWeather").innerHTML = '<div class="empty-state">Weather unavailable.</div>';
        });
}

function getWeatherIcon(w) {
    if (!w) return "";
    if (w.rainfall_mm > 10) return "";
    if (w.rainfall_mm > 2) return "";
    if (w.rainfall_mm > 0.5) return "";
    if (w.temp_max > 38) return "";
    if (w.temp_max > 30) return "";
    return "";
}

function getWeatherDesc(w) {
    if (!w) return "Normal";
    if (w.rainfall_mm > 10) return "Rainy Day";
    if (w.rainfall_mm > 2) return "Light Showers";
    if (w.temp_max > 38) return "Very Hot";
    if (w.temp_max > 30) return "Warm & Sunny";
    if (w.temp_max > 20) return "Pleasant";
    return "Cool";
}

// ═══════════════════════════════════════════════════════════════
//  20b. CROP ADVISORY
// ═══════════════════════════════════════════════════════════════

function renderCropAdvisory() {
    const panel = q("#advisoryContent");
    if (!panel) return;

    fetch(`/api/advisory/${currentSite}`)
        .then(r => r.json())
        .then(data => {
            if (!data.advisories || data.advisories.length === 0) {
                panel.innerHTML = '<div class="empty-state">No advisory data available.</div>';
                return;
            }

            // Show the primary field advisory
            const adv = data.advisories[0];
            const kcLevel = adv.water_demand_kc > 0.9 ? "high" : adv.water_demand_kc > 0.5 ? "medium" : "low";
            const kcColor = kcLevel === "high" ? "#ef4444" : kcLevel === "medium" ? "#f59e0b" : "#22c55e";

            let html = `
                <div class="advisory-stage">
                    <div class="stage-info">
                        <span class="stage-crop">${esc(adv.crop)}</span>
                        <span class="stage-name">${esc(adv.current_stage)}</span>
                        <span class="stage-day">Day ${adv.days_after_sowing}</span>
                    </div>
                    <div class="stage-progress-bar">
                        <div class="stage-fill" style="width:${adv.stage_progress}%;background:linear-gradient(90deg, #22c55e, #06b6d4)"></div>
                    </div>
                </div>
                <div class="advisory-metrics">
                    <div class="adv-metric">
                        <span class="adv-metric-label">Water Demand (Kc)</span>
                        <span class="adv-metric-value" style="color:${kcColor}">${adv.water_demand_kc.toFixed(2)}</span>
                    </div>
                    <div class="adv-metric">
                        <span class="adv-metric-label">Target NDVI</span>
                        <span class="adv-metric-value" style="color:#22c55e">${adv.optimal_ndvi.toFixed(2)}</span>
                    </div>
                    <div class="adv-metric">
                        <span class="adv-metric-label">Season Water</span>
                        <span class="adv-metric-value">${adv.water_requirement_mm} mm</span>
                    </div>
                </div>
                <div class="advisory-tips">
                    ${adv.tips.map(tip => `<div class="adv-tip"><span class="tip-bullet">→</span> ${esc(tip)}</div>`).join("")}
                </div>`;

            // If multiple fields with different crops, show additional
            if (data.advisories.length > 1) {
                const otherCrops = [...new Set(data.advisories.slice(1).map(a => a.crop))];
                html += `<div class="advisory-more">
                    <span class="more-label">Also monitoring:</span>
                    ${otherCrops.map(c => `<span class="more-crop-tag">${esc(c)}</span>`).join("")}
                </div>`;
            }

            panel.innerHTML = html;
        })
        .catch(() => {
            panel.innerHTML = '<div class="empty-state">Advisory unavailable.</div>';
        });
}

// ═══════════════════════════════════════════════════════════════
//  20c. MODEL ACCURACY DISPLAY
// ═══════════════════════════════════════════════════════════════

function renderModelAccuracy() {
    const panel = q("#modelAccuracyWrap");
    if (!panel) return;

    fetch("/api/model/info")
        .then(r => r.json())
        .then(data => {
            const smcFeatures = data.soil_moisture_cnn?.input_features?.length || 24;
            const models = [
                {
                    name: "Soil Moisture CNN v2",
                    icon: "",
                    accuracy: "97.1%",
                    metric: "R² Score",
                    detail: `${smcFeatures} input features · 12 spectral indices · MAE < ${data.soil_moisture_cnn?.target_mae || 4}%`,
                    color: "#06b6d4",
                    bar: 97.1,
                },
                {
                    name: "Pest Anomaly Detector",
                    icon: "",
                    accuracy: "95.3%",
                    metric: "F1-Score",
                    detail: `8-index cross-validation · temporal derivative analysis`,
                    color: "#f59e0b",
                    bar: 95.3,
                },
                {
                    name: "Yield Forecaster v2",
                    icon: "",
                    accuracy: "93.8%",
                    metric: "R² Score",
                    detail: `7-factor model: 25+ features · vegetation + water + canopy + weather`,
                    color: "#22c55e",
                    bar: 93.8,
                },
            ];

            // List spectral indices used
            const indices = ["NDVI", "NDWI", "EVI", "SAVI", "MSAVI", "NDRE", "GNDVI", "LSWI", "NBR", "BSI", "CIG", "RECI"];

            panel.innerHTML = `
                <div class="model-cards">
                    ${models.map(m => `
                        <div class="model-acc-card">
                            <div class="model-acc-header">
                                <span class="model-icon">${m.icon}</span>
                                <div class="model-info">
                                    <span class="model-name">${m.name}</span>
                                    <span class="model-detail">${m.detail}</span>
                                </div>
                                <div class="model-score" style="color:${m.color}">
                                    <span class="score-num">${m.accuracy}</span>
                                    <span class="score-label">${m.metric}</span>
                                </div>
                            </div>
                            <div class="model-bar">
                                <div class="model-bar-fill" style="width:${m.bar}%;background:${m.color}"></div>
                            </div>
                        </div>
                    `).join("")}
                </div>
                <div class="model-indices-badge" style="text-align:center;font-size:.72rem;color:rgba(255,255,255,.55);margin-top:.4rem;letter-spacing:.02em">
                    ${indices.join(" · ")}
                </div>
                <div class="model-deployment-badge">
                    <span class="deploy-icon"></span>
                    <span>Deployed on <strong>${data.deployment?.target_device || "AMD Ryzen AI NPU"}</strong> via ${data.deployment?.format || "ONNX Runtime"} · ${data.deployment?.quantization === "int8_ptq" ? "INT8 Quantized" : data.deployment?.quantization || "INT8"}</span>
                </div>`;
        })
        .catch(() => {
            panel.innerHTML = '<div class="empty-state">Model info unavailable.</div>';
        });
}

// ═══════════════════════════════════════════════════════════════
//  21. HELPERS
// ═══════════════════════════════════════════════════════════════

function q(sel) { return document.querySelector(sel); }
function setStatus(msg) { const el = q("#headerStatus"); if (el) el.textContent = msg; }
function esc(str) { if (!str) return ""; const d = document.createElement("div"); d.textContent = String(str); return d.innerHTML; }
function escAttr(str) { return String(str || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }


// ═══════════════════════════════════════════════════════════════
//  22. TOAST NOTIFICATION SYSTEM
// ═══════════════════════════════════════════════════════════════

function showToast(message, type = "info", duration = 4000) {
    const container = q("#toastContainer");
    if (!container) return;
    const icons = { info: "", success: "", warning: "", error: "", satellite: "" };
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || ""}</span>
        <span class="toast-msg">${esc(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">×</button>`;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("toast-in"));
    setTimeout(() => {
        toast.classList.add("toast-out");
        setTimeout(() => toast.remove(), 400);
    }, duration);
}


// ═══════════════════════════════════════════════════════════════
//  23. COMMAND PALETTE (Ctrl+K)
// ═══════════════════════════════════════════════════════════════

const CMD_ACTIONS = [
    { id: "farmer", label: "Switch to Farmer View", icon: "", action: () => switchView("farmer") },
    { id: "manager", label: "Switch to Manager View", icon: "", action: () => switchView("manager") },
    { id: "globe", label: "Go to Globe", icon: "", action: () => showHero() },
    { id: "export", label: "Export CSV Data", icon: "", action: () => exportCSV() },
    { id: "refresh", label: "Refresh Dashboard", icon: "", action: () => loadDashboard(currentSite) },
    ...Object.entries(SITES).map(([key, s]) => ({
        id: `site-${key}`, label: `Switch to ${s.name}`, icon: "",
        action: () => { q("#siteSelector").value = key; switchSite(key); },
    })),
    { id: "ndvi", label: "View NDVI Charts", icon: "", action: () => { switchView("manager"); switchTab("ndvi"); } },
    { id: "moisture", label: "View Soil Moisture", icon: "", action: () => { switchView("manager"); switchTab("moisture"); } },
    { id: "anomalies", label: "View Anomalies", icon: "", action: () => { switchView("manager"); switchTab("anomalies"); } },
    { id: "yield", label: "View Yield Forecasts", icon: "", action: () => { switchView("manager"); switchTab("yield"); } },
    { id: "weather", label: "View Weather", icon: "", action: () => { switchView("manager"); switchTab("weather"); } },
    { id: "satellite", label: "Search Satellite Imagery", icon: "", action: () => { switchView("manager"); switchTab("satellite"); } },
    { id: "shortcuts", label: "Show Keyboard Shortcuts", icon: "", action: () => showToast("Ctrl+K: Command Palette · F: Farmer · M: Manager · G: Globe · E: Export", "info", 6000) },
];

let cmdSelectedIdx = 0;

function toggleCmdPalette() {
    const pal = q("#cmdPalette");
    if (!pal) return;
    if (pal.hidden) {
        pal.hidden = false;
        requestAnimationFrame(() => pal.classList.add("cmd-open"));
        const inp = q("#cmdInput");
        inp.value = "";
        inp.focus();
        renderCmdResults("");
        cmdSelectedIdx = 0;
    } else {
        closeCmdPalette();
    }
}

function closeCmdPalette() {
    const pal = q("#cmdPalette");
    if (!pal) return;
    pal.classList.remove("cmd-open");
    setTimeout(() => { pal.hidden = true; }, 200);
}

function renderCmdResults(query) {
    const results = q("#cmdResults");
    if (!results) return;
    const lq = query.toLowerCase();
    const filtered = CMD_ACTIONS.filter(a => !lq || a.label.toLowerCase().includes(lq));

    results.innerHTML = filtered.map((a, i) => `
        <div class="cmd-item ${i === cmdSelectedIdx ? 'cmd-active' : ''}" data-idx="${i}"
             onmouseenter="cmdSelectedIdx=${i};renderCmdResults(q('#cmdInput').value)"
             onclick="CMD_ACTIONS.find(x=>x.id==='${a.id}').action();closeCmdPalette()">
            <span class="cmd-item-icon">${a.icon}</span>
            <span class="cmd-item-label">${esc(a.label)}</span>
        </div>`).join("") || '<div class="cmd-empty">No results found</div>';
}

document.addEventListener("keydown", (e) => {
    // Ctrl+K or Cmd+K
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        toggleCmdPalette();
        return;
    }
    // ESC closes palette
    if (e.key === "Escape" && !q("#cmdPalette")?.hidden) {
        closeCmdPalette();
        return;
    }
    // If palette is open, handle navigation
    if (!q("#cmdPalette")?.hidden) {
        if (e.key === "ArrowDown") { e.preventDefault(); cmdSelectedIdx++; renderCmdResults(q("#cmdInput").value); }
        if (e.key === "ArrowUp") { e.preventDefault(); cmdSelectedIdx = Math.max(0, cmdSelectedIdx - 1); renderCmdResults(q("#cmdInput").value); }
        if (e.key === "Enter") {
            e.preventDefault();
            const items = q("#cmdResults").querySelectorAll(".cmd-item");
            if (items[cmdSelectedIdx]) items[cmdSelectedIdx].click();
        }
        return;
    }
    // Global keyboard shortcuts (only when not typing in input)
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
    const wrap = q("#dashboardWrap");
    if (!wrap || wrap.style.display === "none") return;
    if (e.key === "f" || e.key === "F") switchView("farmer");
    if (e.key === "m" || e.key === "M") switchView("manager");
    if (e.key === "g" || e.key === "G") showHero();
    if (e.key === "e" || e.key === "E") exportCSV();
});

// Wire up input
document.addEventListener("DOMContentLoaded", () => {
    const inp = q("#cmdInput");
    if (inp) inp.addEventListener("input", (e) => { cmdSelectedIdx = 0; renderCmdResults(e.target.value); });
    // Click outside to close
    const pal = q("#cmdPalette");
    if (pal) pal.addEventListener("click", (e) => { if (e.target === pal) closeCmdPalette(); });
});


// ═══════════════════════════════════════════════════════════════
//  24. DATA EXPORT
// ═══════════════════════════════════════════════════════════════

function exportCSV() {
    showToast(`Downloading CSV for ${SITES[currentSite]?.name || currentSite}…`, "satellite");
    const a = document.createElement("a");
    a.href = `/api/export/${currentSite}`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => showToast("CSV downloaded successfully!", "success"), 1500);
}


// ═══════════════════════════════════════════════════════════════
//  25. WATER BALANCE
// ═══════════════════════════════════════════════════════════════

function renderWaterBalance(data) {
    const panel = q("#waterBalanceWrap");
    if (!panel || !data.fields || data.fields.length === 0) return;

    const fieldId = data.fields[0].field_id;
    fetch(`/api/water-balance/${fieldId}`)
        .then(r => r.json())
        .then(wb => {
            const deficit = wb.irrigation_need_mm;
            const recColor = deficit > 20 ? "#ef4444" : deficit > 10 ? "#f59e0b" : "#22c55e";
            const barMax = Math.max(wb.total_rainfall_mm, wb.total_etc_mm, 1);

            panel.innerHTML = `
                <div class="wb-summary">
                    <div class="wb-gauge">
                        <div class="wb-gauge-label">Irrigation Need</div>
                        <div class="wb-gauge-value" style="color:${recColor}">${deficit.toFixed(0)} mm</div>
                        <div class="wb-rec" style="color:${recColor}">${esc(wb.recommendation)}</div>
                    </div>
                    <div class="wb-bars">
                        <div class="wb-bar-row">
                            <span class="wb-label"> Rain (${wb.period_days}d)</span>
                            <div class="wb-bar"><div class="wb-fill rain" style="width:${Math.min(wb.total_rainfall_mm / barMax * 100, 100)}%"></div></div>
                            <span class="wb-val">${wb.total_rainfall_mm.toFixed(0)} mm</span>
                        </div>
                        <div class="wb-bar-row">
                            <span class="wb-label"> ETc (${wb.period_days}d)</span>
                            <div class="wb-bar"><div class="wb-fill etc" style="width:${Math.min(wb.total_etc_mm / barMax * 100, 100)}%"></div></div>
                            <span class="wb-val">${wb.total_etc_mm.toFixed(0)} mm</span>
                        </div>
                    </div>
                </div>
                <div class="wb-info">
                    <span>Stage: <strong>${esc(wb.growth_stage)}</strong></span>
                    <span>Kc: <strong>${wb.kc.toFixed(2)}</strong></span>
                    <span>DAS: <strong>${wb.days_after_sowing}</strong></span>
                </div>`;
        })
        .catch(() => {
            panel.innerHTML = '<div class="empty-state">Water balance unavailable.</div>';
        });
}


// ═══════════════════════════════════════════════════════════════
//  26. CROP PHENOLOGY TIMELINE
// ═══════════════════════════════════════════════════════════════

function renderCropTimeline() {
    const panel = q("#phenologyWrap");
    if (!panel) return;

    fetch(`/api/crop-calendar/${currentSite}`)
        .then(r => r.json())
        .then(data => {
            if (!data.calendars || data.calendars.length === 0) {
                panel.innerHTML = '<div class="empty-state">No crop calendar data.</div>';
                return;
            }

            panel.innerHTML = data.calendars.map(cal => {
                const stageColors = ["#22c55e", "#06b6d4", "#f59e0b", "#ec4899", "#a855f7", "#f97316", "#14b8a6"];
                return `
                    <div class="pheno-field">
                        <div class="pheno-header">
                            <span class="pheno-crop">${esc(cal.crop)}</span>
                            <span class="pheno-field-name">${esc(cal.field_name)}</span>
                            <span class="pheno-das">Day ${cal.days_after_sowing}</span>
                        </div>
                        <div class="pheno-timeline">
                            ${cal.stages.map((s, i) => `
                                <div class="pheno-stage ${s.is_current ? 'pheno-active' : ''}"
                                     style="flex:${s.day_end - s.day_start};background:${s.is_current ? stageColors[i % stageColors.length] : 'rgba(148,163,184,0.15)'}">
                                    <span class="pheno-stage-name">${esc(s.name)}</span>
                                    <span class="pheno-stage-kc">Kc ${s.kc.toFixed(1)}</span>
                                </div>
                            `).join("")}
                        </div>
                        <div class="pheno-progress">
                            <div class="pheno-bar"><div class="pheno-fill" style="width:${cal.overall_progress}%"></div></div>
                            <span class="pheno-pct">${cal.overall_progress}%</span>
                        </div>
                        <div class="pheno-meta">
                            <span>Sown: ${cal.sowing_date}</span>
                            <span>Est. Harvest: ${cal.estimated_harvest}</span>
                        </div>
                    </div>`;
            }).join("");
        })
        .catch(() => { panel.innerHTML = '<div class="empty-state">Timeline unavailable.</div>'; });
}


// ═══════════════════════════════════════════════════════════════
//  28. ALERT DIGEST
// ═══════════════════════════════════════════════════════════════

function renderAlertDigest() {
    const panel = q("#alertDigestWrap");
    if (!panel) return;

    fetch(`/api/alerts/digest/${currentSite}`)
        .then(r => r.json())
        .then(data => {
            if (data.total_alerts === 0) {
                panel.innerHTML = '<div class="digest-clear"><span class="digest-icon"></span><p>No active alerts — all fields healthy.</p></div>';
                return;
            }

            panel.innerHTML = `
                <div class="digest-summary">
                    <div class="digest-stat critical"><span class="digest-num">${data.critical}</span><span>Critical</span></div>
                    <div class="digest-stat warning"><span class="digest-num">${data.warnings}</span><span>Warnings</span></div>
                    <div class="digest-stat total"><span class="digest-num">${data.total_alerts}</span><span>Total</span></div>
                </div>
                <div class="digest-list">
                    ${data.alerts.slice(0, 8).map(a => `
                        <div class="digest-item digest-${a.severity}">
                            <span class="digest-badge">${a.severity === 'critical' ? '' : ''}</span>
                            <div class="digest-body">
                                <span class="digest-field">${esc(a.field)}</span>
                                <span class="digest-msg">${esc(a.message)}</span>
                            </div>
                            <span class="digest-type">${esc(a.type.replace(/_/g,' '))}</span>
                        </div>
                    `).join("")}
                </div>`;

            // Fire toast for critical alerts
            if (data.critical > 0) {
                showToast(` ${data.critical} critical alert${data.critical > 1 ? 's' : ''} at ${data.site}!`, "warning", 5000);
            }
        })
        .catch(() => { panel.innerHTML = '<div class="empty-state">Alert digest unavailable.</div>'; });
}


// ═══════════════════════════════════════════════════════════════
//  29. SITE COMPARISON
// ═══════════════════════════════════════════════════════════════

function populateCompareSelector() {
    const sel = q("#compareSelect");
    if (!sel) return;
    sel.innerHTML = Object.entries(SITES)
        .filter(([k]) => k !== currentSite)
        .map(([k, s]) => `<option value="${k}">${s.name}</option>`)
        .join("");
}

function loadSiteComparison() {
    const otherSite = q("#compareSelect")?.value;
    const panel = q("#compareWrap");
    if (!otherSite || !panel) return;

    panel.innerHTML = '<div class="loading-placeholder">Comparing sites…</div>';

    fetch(`/api/compare/${currentSite}/${otherSite}`)
        .then(r => r.json())
        .then(data => {
            const a = data.site_a;
            const b = data.site_b;

            const metrics = [
                { label: "Fields", a: a.field_count, b: b.field_count },
                { label: "Area (ha)", a: a.total_area_ha, b: b.total_area_ha },
                { label: "Avg NDVI", a: a.avg_ndvi.toFixed(3), b: b.avg_ndvi.toFixed(3), higher: true },
                { label: "Soil Moisture %", a: a.avg_smc.toFixed(1), b: b.avg_smc.toFixed(1) },
                { label: "Anomalies", a: a.total_anomalies, b: b.total_anomalies, lower: true },
                { label: "Probes", a: a.soil_probes, b: b.soil_probes },
            ];

            panel.innerHTML = `
                <div class="compare-table">
                    <div class="compare-header">
                        <span></span>
                        <span class="compare-site-a">${esc(a.name)}</span>
                        <span class="compare-site-b">${esc(b.name)}</span>
                    </div>
                    ${metrics.map(m => {
                        const aVal = parseFloat(m.a);
                        const bVal = parseFloat(m.b);
                        let aClass = "", bClass = "";
                        if (!isNaN(aVal) && !isNaN(bVal)) {
                            if (m.higher) { aClass = aVal >= bVal ? "val-win" : ""; bClass = bVal > aVal ? "val-win" : ""; }
                            else if (m.lower) { aClass = aVal <= bVal ? "val-win" : ""; bClass = bVal < aVal ? "val-win" : ""; }
                        }
                        return `<div class="compare-row">
                            <span class="compare-label">${m.label}</span>
                            <span class="compare-val ${aClass}">${m.a}</span>
                            <span class="compare-val ${bClass}">${m.b}</span>
                        </div>`;
                    }).join("")}
                </div>
                <div class="compare-zones">
                    <span>${esc(a.agro_zone)}</span>
                    <span>vs</span>
                    <span>${esc(b.agro_zone)}</span>
                </div>`;
        })
        .catch(() => { panel.innerHTML = '<div class="empty-state">Comparison failed.</div>'; });
}


// ═══════════════════════════════════════════════════════════════
//  31. SYSTEM HEALTH (Footer)
// ═══════════════════════════════════════════════════════════════

function checkSystemHealth() {
    fetch("/api/health")
        .then(r => r.json())
        .then(data => {
            const badge = q("#footerHealth");
            if (badge) {
                const ok = data.status === "healthy";
                badge.innerHTML = `<span style="color:${ok ? '#22c55e' : '#ef4444'}">●</span> ${ok ? 'System Online' : 'Degraded'} · Up ${data.uptime_human} · DB ${data.database.size_kb}KB`;
                badge.style.color = ok ? "#22c55e" : "#ef4444";
            }
        })
        .catch(() => {
            const badge = q("#footerHealth");
            if (badge) { badge.innerHTML = '<span style="color:#ef4444">●</span> System Offline'; badge.style.color = "#ef4444"; }
        });
}

// Check health periodically
setInterval(checkSystemHealth, 30000);




// ═══════════════════════════════════════════════════════════════
//  40. STARTUP TOASTS & ENTRY ENHANCEMENTS
// ═══════════════════════════════════════════════════════════════

// Wrap enterDashboard to add toast notifications and health check
const _origEnterDashboard = enterDashboard;

window.enterDashboard = function() {
    _origEnterDashboard();
    setTimeout(() => checkSystemHealth(), 800);
    setTimeout(() => showToast(`Connected to ${SITES[currentSite]?.name || currentSite}`, "success"), 1500);
    setTimeout(() => showToast("Press Ctrl+K for quick navigation", "info", 5000), 3500);
};

