import AppKit
import Darwin

// User-initiated operations use a different socket from the read-only status feed.
// All I/O/signature work stays off AppKit; an uncertain send is never retried.
final class NyraControlClient {
    let consumer=UUID().uuidString
    var generation=0
    var inspecting=false
    final class RequestLease {
        private let lock=NSLock()
        private var cancelled=false
        let deadline=ProcessInfo.processInfo.systemUptime+4
        func cancel(){lock.lock();cancelled=true;lock.unlock()}
        var valid:Bool {lock.lock();defer{lock.unlock()};return !cancelled && ProcessInfo.processInfo.systemUptime<deadline}
        func whileValid<T>(_ operation:()->T)throws->T {
            lock.lock();defer{lock.unlock()}
            guard !cancelled,ProcessInfo.processInfo.systemUptime<deadline else{throw Failure.deadline}
            return operation()
        }
    }
    var activeMethods=[String:RequestLease]()
    var tasks:[[String:Any]]=[]
    var received:Double=0
    var language="en"
    var authorized=false
    var error:String?
    func reset(){
        generation+=1;activeMethods.values.forEach{$0.cancel()};activeMethods.removeAll()
        tasks=[];received=0;authorized=false;inspecting=false;error=nil
    }
    func request(_ method:String,selection:BridgeSelection?,values:[String:Any]=[:],completion:@escaping([String:Any])->Void) {
        guard let selection=selection else{completion(["error":"HOST_NOT_CONNECTED"]);return}
        guard activeMethods[method]==nil,activeMethods.count<3 else{completion(["error":"CONTROL_REQUEST_PENDING"]);return}
        let lease=RequestLease();activeMethods[method]=lease
        let token=generation,id=UUID().uuidString
        var completed=false
        DispatchQueue.main.asyncAfter(deadline:.now()+4){
            guard !completed else{return};completed=true;lease.cancel()
            if self.activeMethods[method] === lease {self.activeMethods.removeValue(forKey:method)}
            guard self.generation==token else{completion(["error":"HOST_CONNECTION_CHANGED"]);return}
            completion(["error":"CONTROL_DEADLINE_STATUS_UNKNOWN_NO_RETRY"])
        }
        DispatchQueue.global(qos:.userInitiated).async {
            let result: [String:Any]
            do {result=try Self.exchange(method,selection:selection,consumer:self.consumer,id:id,values:values,lease:lease)}
            catch {result=["error":String(describing:error)]}
            DispatchQueue.main.async {
                if self.activeMethods[method] === lease {self.activeMethods.removeValue(forKey:method)}
                guard !completed else{return};completed=true
                guard self.generation==token else{completion(["error":"HOST_CONNECTION_CHANGED"]);return}
                completion(result)
            }
        }
    }
    func inspect(selection:BridgeSelection?,completion:@escaping()->Void) {
        guard !inspecting else{return};inspecting=true;let token=generation
        request("inspect",selection:selection){[weak self] value in
            guard let self=self,self.generation==token else{return};self.inspecting=false
            if let error=value["error"] as? String {self.error=error;self.authorized=false}
            else if let rows=value["tasks"] as? [[String:Any]],rows.count<=2,rows.allSatisfy({
                ["left","right"].contains($0["side"] as? String ?? "") &&
                ["ChatGPT","Claude","DeepSeek","Codex"].contains($0["provider"] as? String ?? "") &&
                ($0["target"] as? String)?.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil &&
                ($0["title"] as? String).map{!$0.isEmpty && $0.count<=90 && $0.rangeOfCharacter(from:.controlCharacters)==nil} == true
            }) {
                self.tasks=rows;self.received=ProcessInfo.processInfo.systemUptime;self.error=nil
                self.authorized=value["userControls"] as? Bool==true;self.language=value["language"] as? String=="zh" ? "zh":"en"
            } else{self.error="INVALID_CONTROL_SNAPSHOT";self.authorized=false}
            completion()
        }
    }
    enum Failure:Error {case controlUnavailable,peerChanged,deadline,invalidResponse,sendStatusUnknown}
    static func exchange(_ method:String,selection:BridgeSelection,consumer:String,id:String,values:[String:Any],lease:RequestLease)throws->[String:Any] {
        guard lease.valid else{throw Failure.deadline}
        let endpoint=try NyraStatusClient.readEndpoint(selection.endpoint)
        guard lease.valid else{throw Failure.deadline}
        guard endpoint.control_protocol=="twos.nyra.control.v1",let path=endpoint.control_socket,
              path=="/private/tmp/twos-nyra-status-"+endpoint.producer_instance_id+"/control.sock" else{throw Failure.controlUnavailable}
        try NyraStatusClient.securePath(path,mode:0o600,socket:true)
        let fd=socket(AF_UNIX,SOCK_STREAM,0);guard fd>=0 else{throw Failure.controlUnavailable};defer{Darwin.close(fd)}
        var noSignal:Int32=1
        guard setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&noSignal,socklen_t(MemoryLayout<Int32>.size))==0,fcntl(fd,F_SETFL,O_NONBLOCK)==0 else{throw Failure.controlUnavailable}
        var address=sockaddr_un();address.sun_family=sa_family_t(AF_UNIX);address.sun_len=UInt8(MemoryLayout<sockaddr_un>.size)
        guard path.utf8.count+1<=MemoryLayout.size(ofValue:address.sun_path) else{throw Failure.controlUnavailable}
        withUnsafeMutableBytes(of:&address.sun_path){b in path.utf8CString.withUnsafeBytes{b.copyMemory(from:$0)}}
        let connected=withUnsafePointer(to:&address){$0.withMemoryRebound(to:sockaddr.self,capacity:1){Darwin.connect(fd,$0,socklen_t(MemoryLayout<sockaddr_un>.size))}}
        func ready(_ event:Int16,_ milliseconds:Int32)throws {
            var p=pollfd(fd:fd,events:event,revents:0)
            guard poll(&p,1,milliseconds)==1,p.revents & event != 0 else{throw Failure.deadline}
        }
        if connected != 0 {guard errno==EINPROGRESS else{throw Failure.controlUnavailable};try ready(Int16(POLLOUT),400)}
        var err:Int32=0;var size=socklen_t(MemoryLayout<Int32>.size)
        guard getsockopt(fd,SOL_SOCKET,SO_ERROR,&err,&size)==0,err==0 else{throw Failure.controlUnavailable}
        let peer=try NyraStatusClient.verifyPeer(fd,selection:selection)
        guard lease.valid else{throw Failure.deadline}
        if method=="focus" {
            // Public cooperative activation, only after exact live-peer validation.
            // The host still restores and confirms its actual workbench window.
            DispatchQueue.main.async {try? lease.whileValid {if !peer.isTerminated { _ = peer.activate(options:[.activateAllWindows]) }}}
        }
        var request=values
        request["protocol"]="twos.nyra.control.v1";request["hostInstance"]=endpoint.producer_instance_id
        request["consumerInstance"]=consumer;request["requestID"]=id;request["method"]=method
        request["issuedUptime"]=ProcessInfo.processInfo.systemUptime
        let bytes=try JSONSerialization.data(withJSONObject:request)+Data([10]);guard bytes.count<=240_000 else{throw Failure.invalidResponse}
        let deadline=lease.deadline
        var offset=0
        while offset<bytes.count {
            guard lease.valid else{throw Failure.sendStatusUnknown}
            try ready(Int16(POLLOUT),200)
            let n=try lease.whileValid {bytes.withUnsafeBytes{Darwin.send(fd,$0.baseAddress!.advanced(by:offset),bytes.count-offset,MSG_DONTWAIT|MSG_NOSIGNAL)}}
            guard n>0 else{throw Failure.sendStatusUnknown};offset+=n
        }
        var data=Data(),buffer=[UInt8](repeating:0,count:8192)
        while lease.valid && ProcessInfo.processInfo.systemUptime<deadline {
            var p=pollfd(fd:fd,events:Int16(POLLIN),revents:0)
            if poll(&p,1,150)==0{continue}
            let n=recv(fd,&buffer,buffer.count,0);guard n>0 else{throw Failure.sendStatusUnknown}
            data.append(contentsOf:buffer.prefix(n));guard data.count<=240_000 else{throw Failure.invalidResponse}
            if let end=data.firstIndex(of:10) {
                guard end==data.count-1,let value=(try? JSONSerialization.jsonObject(with:data.dropLast())) as? [String:Any],
                      value["requestID"] as? String==id,value["hostInstance"] as? String==endpoint.producer_instance_id else{throw Failure.invalidResponse}
                return value
            }
        }
        throw Failure.sendStatusUnknown
    }
}
