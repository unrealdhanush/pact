// Offline render helper, loaded only with ?export=1. Normal playback needs no dependency.
(async()=>{
  const panel=document.createElement('div');
  panel.style.cssText='margin:24px 0;color:#b6c3d8;font-size:13px';
  panel.innerHTML='<button id="exportPreview" style="padding:12px 20px;border-radius:10px">Preview render</button> <button id="exportMovie" style="padding:12px 20px;border-radius:10px">Render MP4</button><p id="exportStatus" role="status">Ready to render 1080p / 30 fps.</p><canvas id="exportCanvas" width="1920" height="1080" style="width:100%;height:auto"></canvas>';
  document.querySelector('main').appendChild(panel);
  const canvas=$('exportCanvas'),ctx=canvas.getContext('2d',{alpha:false}),status=$('exportStatus');
  const width=1920,height=1080,fps=30;
  const css=[...document.querySelectorAll('style')].map(el=>el.textContent).join('\n');
  const image=new Image();
  async function paint(at){
    playing=false;time=at;render();controls();score.pause();
    const frame=$('frame').cloneNode(true);
    frame.querySelector('.fullscreen-exit')?.remove();
    frame.querySelectorAll('.scene:not(.visible)').forEach(el=>el.remove());
    frame.style.cssText=`width:${width}px;height:${height}px;aspect-ratio:auto;border-radius:0;box-shadow:none;margin:0;font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased;--blue:#2879ff;--ink:#17191e`;
    const wrapper=document.createElement('div');
    wrapper.setAttribute('xmlns','http://www.w3.org/1999/xhtml');
    wrapper.style.cssText=`width:${width}px;height:${height}px;margin:0;overflow:hidden`;
    const style=document.createElement('style');style.textContent=css+' .approve-visual{transition:none}';
    wrapper.append(style,frame);
    const markup=new XMLSerializer().serializeToString(wrapper);
    const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">${markup}</foreignObject></svg>`;
    const utf8=new TextEncoder().encode(svg);let binary='';
    for(let i=0;i<utf8.length;i+=32768)binary+=String.fromCharCode(...utf8.subarray(i,i+32768));
    image.src='data:image/svg+xml;base64,'+btoa(binary);
    await image.decode();ctx.clearRect(0,0,width,height);ctx.drawImage(image,0,0);
  }
  async function save(blob,kind){
    const response=await fetch('http://127.0.0.1:8018/'+kind,{method:'POST',headers:{'Content-Type':blob.type},body:blob});
    if(!response.ok)throw new Error('Local file writer returned '+response.status);
  }
  $('exportPreview').onclick=async()=>{
    try{status.textContent='Rendering preview…';await paint(time);await save(await new Promise(resolve=>canvas.toBlob(resolve,'image/png')),'preview');status.textContent='Preview saved.';}
    catch(error){status.textContent='Preview failed: '+error.message;}
  };
  $('exportMovie').onclick=async()=>{
    $('exportMovie').disabled=true;$('exportPreview').disabled=true;
    let audioContext;
    try{
      status.textContent='Preparing encoder and soundtrack…';
      const {Output,Mp4OutputFormat,BufferTarget,CanvasSource,AudioBufferSource,Quality}=await import('/assets/pact-export-lib.mjs');
      const output=new Output({format:new Mp4OutputFormat(),target:new BufferTarget()});
      const video=new CanvasSource(canvas,{codec:'avc',quality:new Quality({bitrate:8000000})});
      const audio=new AudioBufferSource({codec:'aac',quality:new Quality({bitrate:192000})});
      output.addVideoTrack(video,{frameRate:fps});output.addAudioTrack(audio);
      audioContext=new AudioContext({sampleRate:48000});
      const decoded=await audioContext.decodeAudioData(await (await fetch(score.src)).arrayBuffer());
      await output.start();await audio.add(decoded);audio.close();
      for(let i=0;i<duration*fps;i++){
        await paint(i/fps);await video.add(i/fps,1/fps);
        if(i%15===0){status.textContent=`Rendering ${Math.floor(i/(duration*fps)*100)}% · ${(i/fps).toFixed(1)} / 28 seconds`;await new Promise(resolve=>setTimeout(resolve,0));}
      }
      video.close();await output.finalize();
      status.textContent='Saving MP4…';
      const blob=new Blob([output.target.buffer],{type:'video/mp4'});
      await save(blob,'export');
      status.textContent=`MP4 saved · ${(blob.size/1048576).toFixed(1)} MB · 1080p · music included.`;
      await paint(26);
    }catch(error){status.textContent='Export failed: '+error.message;}
    finally{await audioContext?.close();$('exportMovie').disabled=false;$('exportPreview').disabled=false;}
  };
})();
