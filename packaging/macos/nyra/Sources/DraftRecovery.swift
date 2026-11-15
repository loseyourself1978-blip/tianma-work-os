import Foundation
import Darwin

// One bounded recovery slot for the single open editor. This is not a queue:
// restored text is display/copy only until the user reviews it in TWOS.
// All storage work is serialized off AppKit and never contains attachments.
final class CompanionDraftRecovery {
    struct Record:Codable {
        let id:String, target:String, title:String, provider:String, text:String
        let uncertain:Bool
        let createdAt:Double
    }
    enum Failure:Error {case unsafeStorage, invalidRecord}
    let root:URL
    // Editors can close while an acknowledgement is still queued. Share the
    // serializer across store instances so a late clear cannot race a new save.
    private static let io=DispatchQueue(label:"Nyra.draft-recovery",qos:.utility)
    init(root:URL){self.root=root}
    var file:URL{root.appendingPathComponent("task-input-recovery.json")}
    private func directory()throws {
        var st=stat()
        guard lstat(root.path,&st)==0,st.st_uid==getuid(),st.st_mode&S_IFMT==S_IFDIR,
              st.st_mode&0o777==0o700,root.resolvingSymlinksInPath().path==root.standardizedFileURL.path else{throw Failure.unsafeStorage}
    }
    private func read()throws->Record? {
        try directory()
        let fd=Darwin.open(file.path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK)
        if fd<0 {if errno==ENOENT{return nil};throw Failure.unsafeStorage}
        defer{Darwin.close(fd)}
        var st=stat()
        guard fstat(fd,&st)==0,st.st_uid==getuid(),st.st_mode&S_IFMT==S_IFREG,
              st.st_mode&0o777==0o600,st.st_size>0,st.st_size<=400_000 else{throw Failure.unsafeStorage}
        var bytes=[UInt8](repeating:0,count:Int(st.st_size)),offset=0
        while offset<bytes.count {
            let remaining=bytes.count-offset
            let n=bytes.withUnsafeMutableBytes{Darwin.read(fd,$0.baseAddress!.advanced(by:offset),remaining)}
            guard n>0 else{throw Failure.invalidRecord};offset+=n
        }
        let value=try JSONDecoder().decode(Record.self,from:Data(bytes))
        guard UUID(uuidString:value.id) != nil,value.text.utf8.count<=64_000,
              value.title.count<=90,value.provider.count<=32,value.target.count<=128 else{throw Failure.invalidRecord}
        return value
    }
    func load(_ done:@escaping(Result<Record?,Error>)->Void){
        Self.io.async{let result=Result{try self.read()};DispatchQueue.main.async{done(result)}}
    }
    func save(_ value:Record,_ done:@escaping(Bool)->Void){
        Self.io.async {
            let success:Bool
            do {
                try self.directory()
                guard UUID(uuidString:value.id) != nil,value.text.utf8.count<=64_000,
                      value.title.count<=90,value.provider.count<=32,value.target.count<=128 else{throw Failure.invalidRecord}
                let bytes=try JSONEncoder().encode(value)
                let temp=self.root.appendingPathComponent(".draft-recovery-"+UUID().uuidString)
                let fd=Darwin.open(temp.path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0o600)
                guard fd>=0 else{throw Failure.unsafeStorage}
                defer{Darwin.close(fd);Darwin.unlink(temp.path)}
                var offset=0
                while offset<bytes.count {
                    let n=bytes.withUnsafeBytes{Darwin.write(fd,$0.baseAddress!.advanced(by:offset),bytes.count-offset)}
                    guard n>0 else{throw Failure.unsafeStorage};offset+=n
                }
                guard fsync(fd)==0,rename(temp.path,self.file.path)==0 else{throw Failure.unsafeStorage}
                success=true
            } catch{success=false}
            DispatchQueue.main.async{done(success)}
        }
    }
    func clear(id:String,_ done:@escaping(Bool)->Void={_ in}){
        Self.io.async {
            let success:Bool
            do{if try self.read()?.id==id{guard unlink(self.file.path)==0 else{throw Failure.unsafeStorage}};success=true}
            catch{success=false}
            DispatchQueue.main.async{done(success)}
        }
    }
}
