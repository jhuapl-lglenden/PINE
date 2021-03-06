/*(C) 2019 The Johns Hopkins University Applied Physics Laboratory LLC. */

import { Component, OnInit, ViewChild, Inject } from "@angular/core";
import { MatDialog, MatDialogRef, MAT_DIALOG_DATA } from "@angular/material/dialog";

import { Observable, forkJoin } from "rxjs";
import { take } from "rxjs/operators";

import { CollectionRepositoryService } from "../../service/collection-repository/collection-repository.service";
import { EventService } from "../../service/event/event.service";

@Component({
    selector: "app-image-collection-uploader",
    templateUrl: "./image-collection-uploader.component.html",
    styleUrls: ["./image-collection-uploader.component.css"]
})
export class ImageCollectionUploaderComponent implements OnInit {

    public files: FileList;

    constructor(private collections: CollectionRepositoryService,
                private events: EventService) { }

    ngOnInit() {
    }

    public handleFileInput(files: FileList) {
        this.files = files;
    }

    public upload(collectionId: string, showMessage: boolean = true): Observable<number> {
        return new Observable((observer) => {
            if(!this.files || this.files.length == 0) {
                observer.next(0);
                observer.complete();
            } else {
                forkJoin(Array.from(this.files).map(file => this.collections.uploadCollectionImage(collectionId, file.name, file)))
                    .pipe(take(1))
                    .subscribe((results: string[]) => {
                        if(showMessage) {
                            this.events.showUserMessage.emit(`Successfully uploaded ${results.length} images.`);
                        }
                        observer.next(results.length);
                        observer.complete();
                    }, (error) => {
                        observer.error(error);
                        observer.complete();
                    });
            }
        });
    }
}

@Component({
    selector: "app-image-collection-uploader-dialog",
    templateUrl: "./image-collection-uploader.dialog.html",
    styleUrls: ["./image-collection-uploader.dialog.css"]
})
export class ImageCollectionUploaderDialog implements OnInit {

    @ViewChild(ImageCollectionUploaderComponent)
    public uploader: ImageCollectionUploaderComponent;

    constructor(public dialogRef: MatDialogRef<ImageCollectionUploaderComponent>) {
    }

    ngOnInit() { }

    public closeDialog(andSave: boolean) {
        this.dialogRef.close(andSave ? this.uploader : undefined);
    }
}

export function dialog(dialog: MatDialog): Observable<ImageCollectionUploaderComponent> {
    let dialogRef = dialog.open(ImageCollectionUploaderDialog, {
    });
    return dialogRef.afterClosed();
}
