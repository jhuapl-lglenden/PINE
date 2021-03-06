/*(C) 2019 The Johns Hopkins University Applied Physics Laboratory LLC. */

import { Component, OnInit, ElementRef, ViewChild } from "@angular/core";
import { FormBuilder, FormGroup, FormControl, FormArray, Validators, ValidationErrors, AbstractControl, ValidatorFn } from "@angular/forms";
import { MatAutocompleteSelectedEvent, MatChipInputEvent, MatCheckbox } from "@angular/material";
import { Router } from "@angular/router";

import * as Papa from "papaparse";

import { UserChooserComponent } from "../user-chooser/user-chooser.component";
import { LabelChooserComponent } from "../label-chooser/label-chooser.component";

import { AppConfig } from "../../app.config";
import { AuthService } from "../../service/auth/auth.service";
import { CollectionRepositoryService } from "../../service/collection-repository/collection-repository.service";
import { EventService } from "../../service/event/event.service";
import { PipelineService } from "../../service/pipeline/pipeline.service";
import { LineReader } from "../../service/utils";

import { Collection, CONFIG_ALLOW_OVERLAPPING_NER_ANNOTATIONS } from "../../model/collection";
import { User } from "../../model/user";
import { Pipeline } from "../../model/pipeline";

@Component({
    selector: "app-metrics-display",
    templateUrl: "./metrics-display.component.html",
    styleUrls: ["./metrics-display.component.css"]
})
export class MetricsDisplayComponent implements OnInit {

    public static readonly SUBTITLE = "Display Metrics";

    public createForm: FormGroup;
    private csvFile: File;
    private pipelines: Pipeline[];
    public loading = false;
    public submitted = false;
    public hadError = false;
    public errorMessage: string;
    private manualFormError = false;
    private hasCsvFile = false;
    private csvHeader = null;
    public configAllowOverlappingNerAnnotations = true;

    @ViewChild("annotators") public annotators: UserChooserComponent;
    @ViewChild("viewers") public viewers: UserChooserComponent;
    @ViewChild("labels") public labels: LabelChooserComponent;
    @ViewChild("file") public file: ElementRef;

    constructor(public appConfig: AppConfig,
                private auth: AuthService,
                private collectionRepository: CollectionRepositoryService,
                private formBuilder: FormBuilder,
                private router: Router,
                private event: EventService,
                private pipeline: PipelineService) {
    }

    ngOnInit() {
        this.loading = true;
        let name = this.auth.loggedInUser.display_name;
        this.createForm = this.formBuilder.group({
            creator_name: [{value: name, disabled: true},
                           Validators.required],
                           creator_id: [{value: this.auth.loggedInUser.id, disabled: true},
                                        Validators.required],
                                        csv_file: [{value: null, disabled: false}],
                                        csv_has_header: [{value: null, disabled: false}],
                                        csv_text_col: [{value: null, disabled: false}],
                                        train_every: [{value: 100, disabled: false}, [Validators.required, Validators.min(1)]],
                                        overlap: [{value: 0, disabled: false}, [Validators.required, Validators.max(1), Validators.min(0)]],
                                        pipeline_id: [{value: null, disabled: false}, Validators.required],
                                        classifier_parameters: [{value: null, disabled: false}, this.classifierParametersJsonValidator()],
                                        metadata_title: [{value: null, disabled: false}, Validators.required],
                                        metadata_description: [{value: null, disabled: false}, Validators.required],
                                        metadata_subject: [{value: null, disabled: false}],
                                        metadata_publisher: [{value: null, disabled: false}],
                                        metadata_contributor: [{value: null, disabled: false}],
                                        metadata_date: [{value: null, disabled: false}],
                                        metadata_type: [{value: null, disabled: false}],
                                        metadata_format: [{value: null, disabled: false}],
                                        metadata_identifier: [{value: null, disabled: false}],
                                        metadata_source: [{value: null, disabled: false}],
                                        metadata_language: [{value: null, disabled: false}],
                                        metadata_relation: [{value: null, disabled: false}],
                                        metadata_coverage: [{value: null, disabled: false}],
                                        metadata_rights: [{value: null, disabled: false}]
        });
        this.csvFile = null;
        this.pipeline.getAllPipelines().subscribe((pipelines: Pipeline[]) => {
            this.pipelines = pipelines;
            this.loading = false;
        }, (error) => {
            alert("Unable to load backend data (check console).");
            console.log(error);
        });
    }

    private classifierParametersJsonValidator(): ValidatorFn {
        return (control: AbstractControl): {[key: string]: any} | null => {
            if(!control.value) { return null; }
            try {
                const value = JSON.parse(control.value);
                if(value instanceof Object) {
                    return null;
                } else {
                    return {"invalid_json": {"error": "Needs to be object and not " + typeof(value)}};
                }
            } catch(e) {
                return {"invalid_json": {"error": e.message}};
            }
        };
    }

    public pipelineDescription(pipeline_id: string): string {
        for(const pipeline of this.pipelines) {
            if(pipeline._id === pipeline_id) {
                return pipeline.description;
            }
        }
        return null;
    }

    public handleFileInput(files: FileList) {
        this.f.csv_file.setValue(files[0].name);
        this.csvFile = files[0];
        const reader = new LineReader(this.csvFile);
        reader.read().subscribe((line: string) => {
            if(line.length > 0) {
                const results = Papa.parse(line, {header: false});
                this.csvHeader = results.data[0];
                this.f.csv_has_header.setValue(this.csvHeader.length > 1);
                this.f.csv_text_col.setValue(0);
                if(this.f.csv_has_header.value) {
                    for(let i = 0; i < this.csvHeader.length; i++) {
                        const header = this.csvHeader[i];
                        if(header.localeCompare("text") === 0) {
                            this.f.csv_text_col.setValue(i);
                            break;
                        }
                    }
                }
                this.hasCsvFile = true;
                reader.cancel();
            }
        });
    }

    public clickAddFile() {
        this.file.nativeElement.click();
    }

    // convenience getter for easy access to form fields
    get f() { return this.createForm.controls; }

    public viewersOrAnnotatorsChanged() {
        const viewers = this.viewers.getChosenUserIds();
        const annotators = this.annotators.getChosenUserIds();
        for(let i = 0; i < annotators.length; i++) {
            const annotatorId = annotators[i];
            if(viewers.indexOf(annotatorId) < 0) {
                this.annotators.setError("All annotators must also be viewers.");
                this.manualFormError = true;
                return;
            }
        }
        this.manualFormError = false;
        this.annotators.clearError();
    }

    public labelAdded() {
        this.labels.clearError();
    }

    public create() {
        this.submitted = true;

        const labels = this.labels.getChosenLabels();
        if(labels.length === 0) {
            this.labels.showError("At least one label is required.");
            return;
        } else {
            this.labels.clearError();
        }

        if(this.createForm.invalid || this.manualFormError) {
            return;
        }

        const collection = <Collection>{};
        collection.creator_id = this.f.creator_id.value;
        collection.annotators = this.annotators.getChosenUserIds();
        collection.viewers = this.viewers.getChosenUserIds();
        collection.labels = labels;
        collection.metadata = {
            title: this.f.metadata_title.value,
            subject: this.f.metadata_subject.value,
            description: this.f.metadata_description.value,
            publisher: this.f.metadata_publisher.value,
            contributor: this.f.metadata_contributor.value,
            date: this.f.metadata_date.value,
            type: this.f.metadata_type.value,
            format: this.f.metadata_format.value,
            identifier: this.f.metadata_identifier.value,
            source: this.f.metadata_source.value,
            language: this.f.metadata_language.value,
            relation: this.f.metadata_relation.value,
            coverage: this.f.metadata_coverage.value,
            rights: this.f.metadata_rights.value
        };
        collection.archived = false;
        collection.configuration = {};
        collection.configuration[CONFIG_ALLOW_OVERLAPPING_NER_ANNOTATIONS] = this.configAllowOverlappingNerAnnotations;
        let csvTextCol = 0;
        let csvHasHeader = false;
        if(this.hasCsvFile) {
            csvHasHeader = this.f.csv_has_header.value;
            if(csvHasHeader) {
                csvTextCol = this.f.csv_text_col.value;
            }
        }
        console.log("Creating collection:");
        console.log(collection);

        this.hadError = false;
        this.errorMessage = null;
        this.collectionRepository.postCollection(collection, this.csvFile, csvTextCol, csvHasHeader,
                this.f.overlap.value, this.f.train_every.value, this.f.pipeline_id.value,
                JSON.parse(this.f.classifier_parameters.value)).subscribe(
            (createdCollection: Collection) => {
                const collectionId = createdCollection._id;
                this.event.showUserMessage.emit("Successfully added collection with ID " + collectionId);
                this.event.collectionAddedOrArchived.emit(createdCollection);
                this.router.navigate(["collectionDetails/" + collectionId]);
            },
            (error) => {
                this.errorMessage = "Error: " + JSON.stringify(error["error"]);
                this.hadError = true;
            }
        );
    }

}
