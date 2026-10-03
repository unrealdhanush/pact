// Existing SF road geometry is embedded; no route API or geolocation is used.
(function(scope){
const ROUTE=[[37.6547,-122.4077],[37.65471,-122.4077],[37.65505,-122.40744],[37.65498,-122.40688],[37.65502,-122.40662],[37.65523,-122.40649],[37.65606,-122.40635],[37.6566,-122.40616],[37.65895,-122.40506],[37.65983,-122.40443],[37.66074,-122.40351],[37.66146,-122.40251],[37.66378,-122.39891],[37.66448,-122.39795],[37.66528,-122.39702],[37.66608,-122.3962],[37.67005,-122.3924],[37.67092,-122.39166],[37.67181,-122.39097],[37.67273,-122.39035],[37.6734,-122.38994],[37.67436,-122.38941],[37.67513,-122.38904],[37.67612,-122.38864],[37.67715,-122.38838],[37.6782,-122.38828],[37.67925,-122.38836],[37.68029,-122.38857],[37.68236,-122.38899],[37.69346,-122.3915],[37.70134,-122.39327],[37.70636,-122.39441],[37.7079,-122.39475],[37.70942,-122.3951],[37.71122,-122.39551],[37.71175,-122.39567],[37.71224,-122.39586],[37.71274,-122.39611],[37.71321,-122.39641],[37.71366,-122.39675],[37.71521,-122.39802],[37.71566,-122.39833],[37.71615,-122.39859],[37.71664,-122.3988],[37.71715,-122.39897],[37.71972,-122.39966],[37.72164,-122.40027],[37.72396,-122.40122],[37.72625,-122.40193],[37.72841,-122.40266],[37.72906,-122.40295],[37.73006,-122.40344],[37.73248,-122.40457],[37.73363,-122.40502],[37.73443,-122.40501],[37.73519,-122.40475],[37.73588,-122.40425],[37.73687,-122.40292],[37.73758,-122.40195],[37.73842,-122.40105],[37.73939,-122.40011],[37.74365,-122.39624],[37.74446,-122.39536],[37.74543,-122.39449],[37.74644,-122.39379],[37.74692,-122.39349],[37.74999,-122.39177],[37.75047,-122.39155],[37.75097,-122.39138],[37.75149,-122.39127],[37.75201,-122.39122],[37.75253,-122.39122],[37.75305,-122.39127],[37.75357,-122.39139],[37.75486,-122.39184],[37.75538,-122.39199],[37.75589,-122.39211],[37.75642,-122.39219],[37.75695,-122.39223],[37.75837,-122.39222],[37.75897,-122.39222],[37.76007,-122.39227],[37.76114,-122.39229],[37.76221,-122.39229],[37.76354,-122.39245],[37.76415,-122.39218],[37.76419,-122.39154],[37.76428,-122.39013],[37.76434,-122.38907],[37.76436,-122.38885],[37.76507,-122.38883],[37.76564,-122.3889],[37.76652,-122.38893],[37.76703,-122.389],[37.76761,-122.38908],[37.76876,-122.38918],[37.76979,-122.38928],[37.77064,-122.38936],[37.77106,-122.38941],[37.77195,-122.3895],[37.77259,-122.38955],[37.77301,-122.38959],[37.77445,-122.38972],[37.77477,-122.3898],[37.77543,-122.38995],[37.77619,-122.39003],[37.77652,-122.3901],[37.77708,-122.39055],[37.77723,-122.39079],[37.77749,-122.39107],[37.77762,-122.39124],[37.77798,-122.39169],[37.77822,-122.392],[37.77937,-122.39342],[37.7801,-122.39432],[37.78065,-122.39501],[37.78109,-122.39556],[37.78165,-122.39626],[37.7821,-122.39683],[37.7824,-122.3972],[37.7827,-122.39758],[37.78344,-122.39851],[37.78386,-122.39904],[37.78435,-122.39965],[37.78494,-122.40038],[37.78583,-122.40151],[37.78626,-122.40204],[37.78703,-122.40302],[37.78739,-122.4034],[37.78768,-122.40344],[37.78788,-122.40348],[37.78844,-122.40359],[37.78935,-122.40377],[37.78983,-122.40387],[37.79068,-122.40404],[37.79134,-122.40417],[37.79179,-122.40425],[37.79256,-122.40441],[37.79254,-122.40532],[37.79245,-122.40603],[37.79226,-122.40755],[37.79208,-122.40895],[37.79205,-122.40918],[37.79199,-122.40967],[37.79184,-122.41083],[37.79164,-122.41239],[37.79158,-122.4129],[37.79142,-122.41412],[37.7912,-122.41585],[37.79101,-122.41731],[37.7908,-122.41897],[37.7906,-122.42061],[37.79055,-122.42132],[37.79043,-122.42231],[37.79024,-122.42372],[37.79013,-122.42428],[37.78976,-122.42719],[37.78954,-122.42892],[37.78934,-122.43049],[37.78912,-122.43221],[37.78892,-122.43376],[37.78879,-122.43479],[37.7887,-122.4355],[37.78865,-122.43592],[37.78848,-122.43724],[37.78827,-122.43889],[37.78837,-122.44052],[37.78977,-122.4408],[37.78999,-122.44085],[37.79068,-122.44098],[37.79154,-122.44116],[37.79171,-122.44119],[37.79252,-122.44136],[37.79344,-122.44154],[37.79439,-122.44173],[37.79525,-122.44191],[37.79615,-122.44209],[37.79709,-122.44228],[37.79729,-122.44232],[37.7982,-122.4425],[37.79889,-122.44264],[37.79901,-122.44302],[37.79887,-122.44415],[37.79886,-122.44446],[37.79888,-122.44473],[37.79884,-122.44497],[37.79872,-122.44527],[37.79862,-122.44608],[37.79849,-122.4471],[37.79846,-122.44746],[37.79843,-122.44767],[37.79835,-122.44792],[37.79821,-122.44807],[37.79791,-122.44829],[37.79778,-122.44845],[37.79763,-122.44875],[37.79753,-122.44909],[37.79744,-122.44958],[37.79745,-122.45017],[37.79757,-122.45073],[37.79765,-122.45101],[37.79761,-122.45127],[37.79793,-122.45145],[37.79834,-122.45171],[37.79877,-122.45208],[37.79892,-122.45228],[37.7993,-122.45269],[37.79953,-122.45281],[37.79994,-122.45291],[37.80007,-122.45296],[37.80019,-122.45305],[37.80029,-122.45317],[37.80035,-122.45326],[37.80054,-122.45363],[37.80059,-122.45372],[37.80063,-122.45372],[37.80067,-122.45374],[37.80069,-122.45378],[37.8007,-122.45382],[37.80069,-122.45386],[37.80067,-122.45389],[37.80069,-122.45407],[37.80098,-122.45482],[37.80127,-122.45551],[37.80162,-122.45629],[37.80171,-122.45656],[37.80177,-122.45693],[37.80197,-122.45764],[37.80196,-122.45788],[37.802,-122.45808],[37.80212,-122.45847],[37.80147,-122.45905]];
const HUB_INDEX = 97;
const STAGE_INDEX = [0, 0, HUB_INDEX, Math.round(HUB_INDEX + (ROUTE.length - 1 - HUB_INDEX) * .6), ROUTE.length - 1];
const radians = value => value * Math.PI / 180;
const distances = [0];
for (let i=1;i<ROUTE.length;i++) {
  const [a,b] = [ROUTE[i-1],ROUTE[i]];
  const h = Math.sin(radians(b[0]-a[0])/2)**2 + Math.cos(radians(a[0]))*Math.cos(radians(b[0]))*Math.sin(radians(b[1]-a[1])/2)**2;
  distances.push(distances[i-1] + 6371000*2*Math.atan2(Math.sqrt(h),Math.sqrt(1-h)));
}
const totalDistance = distances.at(-1);
const stageProgress = STAGE_INDEX.map(index=>distances[index]/totalDistance);
const clamp = value => Math.max(0,Math.min(1,value));
function sampleRoute(progress) {
  const distance=clamp(progress)*totalDistance;
  let index=0;
  while (index<ROUTE.length-2&&distances[index+1]<distance) index++;
  const fraction=(distance-distances[index])/Math.max(.0001,distances[index+1]-distances[index]);
  const point=ROUTE[index].map((value,axis)=>value+(ROUTE[index+1][axis]-value)*fraction);
  return {point,path:[...ROUTE.slice(0,index+1),point],index};
}
const truck='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h11v11H3zM14 10h4l3 4v3h-7"/><circle cx="7" cy="18" r="2" fill="currentColor" stroke="none"/><circle cx="18" cy="18" r="2" fill="currentColor" stroke="none"/></svg>';
const check='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';
const labels=['Confirmed','Packed','Shipped','Out for delivery','Delivered'];
const stops=[{index:0,title:'Warehouse',place:'South San Francisco',direction:'right'}, {index:HUB_INDEX,title:'Sorting hub',place:'Mission Bay',direction:'right'}, {index:ROUTE.length-1,title:'Destination',place:'Presidio',direction:'left'}];
// The outline uses the same embedded real route, without needing tiles or location access.
const mercator=([lat,lng])=>[radians(lng),Math.log(Math.tan(Math.PI/4+radians(lat)/2))];
const projected=ROUTE.map(mercator),xs=projected.map(p=>p[0]),ys=projected.map(p=>p[1]);
const bounds={left:Math.min(...xs),right:Math.max(...xs),top:Math.max(...ys),bottom:Math.min(...ys)};
function project(point,{width=620,height=350}={}) {
  const [x,y]=mercator(point);
  const scale=Math.min(Math.max(140,width-240)/(bounds.right-bounds.left),Math.max(160,height-140)/(bounds.top-bounds.bottom));
  return [width/2+(x-(bounds.left+bounds.right)/2)*scale,height/2+15-(y-(bounds.top+bounds.bottom)/2)*scale];
}
const pathD = (points,size)=>points.map((point,i)=>`${i?'L':'M'}${project(point,size).map(value=>value.toFixed(2)).join(' ')}`).join(' ');
let nextInstance=0;
class DeliveryMap {
  constructor(root) {
    this.root=root;this.progress=0;this.animation=null;this.map=null;this.preview=false;this.stage=0;this.manualView=false;this.disposed=false;
    this.reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
    root.innerHTML=`<div class="map-canvas" data-map-instance="${++nextInstance}" data-map-mode="outline">
      ${this.outline()}
      <div class="leafmap-layer" role="img" aria-label="Simulated delivery route through San Francisco" aria-hidden="true"></div>
      <div class="map-view-label"><strong>San Francisco</strong><small class="map-mode-label">Route overview</small><small class="map-preview-label">Route preview</small></div>
      <div class="map-tools" aria-label="Map controls"><button type="button" class="map-tool" data-action="in" aria-label="Zoom in on delivery map">+</button><button type="button" class="map-tool" data-action="out" aria-label="Zoom out on delivery map">−</button><button type="button" class="map-tool" data-action="fit" aria-label="Show full delivery route"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M7 3H3v4M13 3h4v4M3 13v4h4M17 13v4h-4M6 6l8 8M14 6l-8 8"/></svg></button></div></div>`;
    this.surface=root.querySelector('.map-canvas');
    this.svg=root.querySelector('.map-outline');
    this.fallbackLine=root.querySelector('[data-progress-path]');
    this.fallbackCourier=root.querySelector('[data-courier]');
    this.layer=root.querySelector('.leafmap-layer');
    this.createMap();this.resizeOutline();this.paint();
    this.resizeObserver=new ResizeObserver(()=>{if(this.disposed||!this.root.isConnected)return;this.resizeOutline();this.paint();if(this.map){this.map.invalidateSize({pan:false});this.alignLabels();if(!this.manualView)this.fit();}});
    this.resizeObserver.observe(this.root);
  }
  outline() {
    return `<svg class="map-outline" viewBox="0 0 620 350" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Delivery route outline: South San Francisco, Mission Bay, Presidio">
      <defs><linearGradient id="delivery-wash" x2="1" y2=".4"><stop stop-color="#eef1e9"/><stop offset="1" stop-color="#e7f0f2"/></linearGradient><pattern id="delivery-grid" width="38" height="38" patternUnits="userSpaceOnUse"><path d="M38 0H0V38" fill="none" stroke="#fff" stroke-width="1.8"/></pattern></defs>
      <rect width="100%" height="100%" fill="url(#delivery-wash)"/><rect width="100%" height="100%" fill="url(#delivery-grid)" opacity=".5"/>
      <g fill="#d9e4d0" opacity=".45"><rect x="45" y="99" width="100" height="64" rx="22"/><rect x="94" y="233" width="81" height="55" rx="15"/></g>
      <g fill="#bbc7cd" font-family="-apple-system,BlinkMacSystemFont,sans-serif" font-size="11" letter-spacing="2"><text x="405" y="180">BAY AREA</text><text x="85" y="205" font-size="9">ROUTE OUTLINE</text></g>
      <path data-route-outline d="${pathD(ROUTE)}" fill="none" stroke="#ffffff" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
      <path data-route-outline d="${pathD(ROUTE)}" fill="none" stroke="#a8bed0" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 7"/>
      <path data-progress-path fill="none" stroke="#2879d0" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
      ${stops.map((stop,i)=>{const[x,y]=project(ROUTE[stop.index]),right=stop.direction==='right';return `<g><circle data-outline-stop="${i}" cx="${x}" cy="${y}" r="8" fill="#8c9ead" stroke="#fff" stroke-width="3"/><text data-stop-title="${i}" x="${x+(right?17:-17)}" y="${y-2}" text-anchor="${right?'start':'end'}" fill="#455f74" font-size="11" font-weight="600">${stop.title}</text><text data-stop-place="${i}" x="${x+(right?17:-17)}" y="${y+12}" text-anchor="${right?'start':'end'}" fill="#8b9ba8" font-size="9">${stop.place}</text></g>`;}).join('')}
      <g data-courier><circle r="22" fill="#2879d0" opacity=".1"/><circle data-courier-disc r="15" fill="#2879d0" stroke="#fff" stroke-width="3"/><g data-courier-art transform="translate(-9 -9)" color="#fff">${truck.replace('<svg ','<svg width="18" height="18" ')}</g></g>
    </svg>`;
  }
  resizeOutline() {
    this.projectionSize={width:this.surface.clientWidth||620,height:this.surface.clientHeight||350};
    this.svg.setAttribute('viewBox',`0 0 ${this.projectionSize.width} ${this.projectionSize.height}`);
    this.root.querySelectorAll('[data-route-outline]').forEach(path=>path.setAttribute('d',pathD(ROUTE,this.projectionSize)));
    stops.forEach((stop,i)=>{const[x,y]=project(ROUTE[stop.index],this.projectionSize),right=this.projectionSize.width>=500&&stop.direction==='right';
      const dot=this.root.querySelector(`[data-outline-stop="${i}"]`);dot.setAttribute('cx',x);dot.setAttribute('cy',y);
      const title=this.root.querySelector(`[data-stop-title="${i}"]`),place=this.root.querySelector(`[data-stop-place="${i}"]`);
      [title,place].forEach(el=>{el.setAttribute('x',x+(right?17:-17));el.setAttribute('text-anchor',right?'start':'end');});title.setAttribute('y',y-2);place.setAttribute('y',y+12);
    });
  }
  createMap() {
    if(!scope.L){this.root.querySelector('.map-mode-label').textContent='Route outline · offline';return;}
    try {
      const L=scope.L;
      this.map=L.map(this.layer,{zoomControl:false,attributionControl:true,scrollWheelZoom:false,dragging:!L.Browser.mobile,doubleClickZoom:false,boxZoom:false,keyboard:false,touchZoom:false,zoomSnap:.25,zoomDelta:.5,minZoom:10,maxZoom:16,zoomAnimation:!this.reducedMotion,fadeAnimation:!this.reducedMotion});
      this.map.attributionControl.setPrefix(false);
      const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'});
      let loaded=0;
      tiles.on('tileload',()=>{if(this.disposed)return;loaded++;this.surface.classList.add('live-tiles');this.surface.dataset.mapMode='tiles';this.layer.setAttribute('aria-hidden','false');this.svg.setAttribute('aria-hidden','true');this.root.querySelector('.map-mode-label').textContent='Real roads · simulated courier';});
      tiles.on('tileerror',()=>{if(!loaded&&!this.disposed)this.root.querySelector('.map-mode-label').textContent='Route outline · offline';});
      tiles.addTo(this.map);
      L.polyline(ROUTE,{color:'#fff',weight:9,opacity:.95,interactive:false}).addTo(this.map);
      L.polyline(ROUTE,{color:'#a7bdce',weight:4,dashArray:'4 7',opacity:.95,interactive:false}).addTo(this.map);
      this.completed=L.polyline([ROUTE[0]],{color:'#2879d0',weight:4.5,opacity:1,interactive:false}).addTo(this.map);
      this.pins=stops.map((stop,i)=>L.marker(ROUTE[stop.index],{interactive:false,keyboard:false,icon:L.divIcon({className:'delivery-stop',html:`<span>${i+1}</span>`,iconSize:[22,22],iconAnchor:[11,11]})}).addTo(this.map).bindTooltip(`<b>${stop.title}</b>${stop.place}`,{permanent:true,direction:stop.direction,offset:stop.direction==='right'?[13,0]:[-13,0],className:'delivery-stop-label',opacity:1}));
      this.van=L.marker(ROUTE[0],{interactive:false,keyboard:false,zIndexOffset:1000,icon:L.divIcon({className:'courier-marker',html:`<span class="courier-disc">${truck}</span>`,iconSize:[34,34],iconAnchor:[17,17]})}).addTo(this.map);
      this.map.on('dragstart',()=>this.manualView=true);
      this.map.on('zoomend',()=>this.updateZoomButtons());
      this.root.querySelectorAll('[data-action]').forEach(button=>button.onclick=()=>{const action=button.dataset.action;if(action==='fit'){this.manualView=false;this.fit(true);}else{this.manualView=true;action==='in'?this.map.zoomIn(.5):this.map.zoomOut(.5);}});
      this.fit();
    }catch { this.map?.remove();this.map=null;this.surface.classList.remove('live-tiles');this.root.querySelector('.map-mode-label').textContent='Route outline · offline'; }
  }
  fit(animate=false) {
    if(!this.map||!this.root.clientWidth)return;
    this.alignLabels();
    const narrow=this.root.clientWidth<500;
    this.map.fitBounds(scope.L.latLngBounds(ROUTE),{paddingTopLeft:narrow?[55,90]:[70,65],paddingBottomRight:narrow?[65,45]:[80,40],animate:animate&&!this.reducedMotion});
    this.updateZoomButtons();
  }
  alignLabels() {
    if(!this.pins)return;
    this.pins.forEach((pin,i)=>{const direction=this.root.clientWidth<500?'left':stops[i].direction,tooltip=pin.getTooltip();
      scope.L.setOptions(tooltip,{direction,offset:direction==='right'?[13,0]:[-13,0]});tooltip.update();
    });
  }
  updateZoomButtons() {
    if(!this.map)return;
    this.root.querySelector('[data-action="in"]').disabled=this.map.getZoom()>=16;
    this.root.querySelector('[data-action="out"]').disabled=this.map.getZoom()<=10;
  }
  update(stage,{preview=false,reset=false,animate=true}={}) {
    this.cancelAnimation();this.stage=stage;this.preview=preview;
    this.surface.classList.toggle('previewing',preview);
    this.root.querySelector('.map-preview-label').textContent=`Route preview · ${labels[stage]}`;
    const description=`${preview?'Preview of':'Simulated'} delivery route: South San Francisco to Mission Bay to Presidio. ${labels[stage]}.`;
    this.svg.setAttribute('aria-label',description);this.layer.setAttribute('aria-label',description);
    const target=preview||reset?stageProgress[stage]:Math.max(this.progress,stageProgress[stage]);
    if(reset||!animate||this.reducedMotion||document.hidden||Math.abs(target-this.progress)<.00001){this.progress=target;this.paint();return;}
    const from=this.progress,started=performance.now(),duration=preview?1750:Math.min(2300,950+Math.abs(target-from)*1900);
    const step=now=>{
      if(this.disposed)return;
      const t=clamp((now-started)/duration),eased=t*t*t*(t*(6*t-15)+10);
      this.progress=from+(target-from)*eased;this.paint();
      if(t<1)this.animation=requestAnimationFrame(step);else this.animation=null;
    };
    this.animation=requestAnimationFrame(step);
  }
  paint() {
    const {point,path}=sampleRoute(this.progress),arrived=this.stage===4&&this.progress>.99999;
    const color=arrived?'#2f8865':'#2879d0';
    this.surface.dataset.routeProgress=this.progress.toFixed(5);
    this.fallbackLine.setAttribute('d',pathD(path,this.projectionSize));this.fallbackLine.setAttribute('stroke',color);
    this.fallbackCourier.setAttribute('transform',`translate(${project(point,this.projectionSize).join(' ')})`);
    this.fallbackCourier.querySelector('[data-courier-disc]').setAttribute('fill',color);
    if(this.wasArrived!==arrived){this.fallbackCourier.querySelector('[data-courier-art]').innerHTML=(arrived?check:truck).replace('<svg ','<svg width="18" height="18" ');this.wasArrived=arrived;}
    stops.forEach((stop,i)=>{const passed=this.progress+1e-6>=distances[stop.index]/totalDistance;this.root.querySelector(`[data-outline-stop="${i}"]`).setAttribute('fill',passed?color:'#8c9ead');const pin=this.pins?.[i].getElement();if(pin){pin.classList.toggle('passed',passed);pin.classList.toggle('finished',arrived);}});
    if(this.map&&this.van){this.van.setLatLng(point);this.completed.setLatLngs(path);this.completed.setStyle({color});const icon=this.van.getElement();icon?.classList.toggle('arrived',arrived);if(icon&&this.lastVanArrived!==arrived){icon.querySelector('.courier-disc').innerHTML=arrived?check:truck;this.lastVanArrived=arrived;}}
  }
  cancelAnimation() {if(this.animation)cancelAnimationFrame(this.animation);this.animation=null;}
  destroy() {this.disposed=true;this.cancelAnimation();this.resizeObserver?.disconnect();this.map?.remove();this.map=null;}
}
scope.PactDeliveryMap=DeliveryMap;
if(typeof module!=='undefined'&&module.exports)module.exports={ROUTE,stageProgress,sampleRoute,totalDistance};
})(typeof window!=='undefined'?window:globalThis);
